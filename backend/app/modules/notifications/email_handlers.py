"""Transactional email delivery (consumer ``email-worker``).

Exactly-once *sending* on top of at-least-once delivery: every email has an ``EmailDelivery`` row keyed by
``{event_id}:{template}``. The row is claimed, and any single-use token issued, in a short transaction that
commits *before* the SMTP call, and it is marked SENT in another short transaction right after. A redelivered
event therefore never sends twice, and a failed send is retried with a fresh token (issuing one invalidates
the previous). Raw tokens exist only in memory between issuance and handing the message to the backend.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import get_sessionmaker
from app.messaging.events import EventEnvelope, EventType, Topics
from app.messaging.registry import on
from app.modules.notifications import email as mail
from app.modules.notifications import preferences as prefs
from app.modules.notifications.models import (
    EmailDelivery,
    EmailStatus,
    Notification,
    NotificationPreference,
    NotificationType,
)
from app.modules.users.models import User

logger = get_logger(__name__)

CONSUMER = "email-worker"
TOPICS = [Topics.EMAIL, Topics.NOTIFICATION]

Prepare = Callable[[AsyncSession], Awaitable[mail.RenderedEmail]]


def idempotency_key(event_id: uuid.UUID, template: str) -> str:
    return f"{event_id}:{template}"


async def _claim(
    session: AsyncSession, *, key: str, user_id: uuid.UUID | None, to: str, template: str
) -> uuid.UUID | None:
    """Create or re-arm the delivery row. Returns None when this email was already SENT."""
    stmt = insert(EmailDelivery).values(
        id=uuid.uuid4(),
        user_id=user_id,
        to_address=to,
        template=template,
        subject=template,
        idempotency_key=key,
        status=EmailStatus.PENDING,
        attempts=1,
    )
    upsert = stmt.on_conflict_do_update(
        constraint="uq_email_deliveries_idempotency",
        set_={"attempts": EmailDelivery.attempts + 1, "status": EmailStatus.PENDING, "to_address": to},
        where=EmailDelivery.status != EmailStatus.SENT,
    ).returning(EmailDelivery.id)
    return (await session.execute(upsert)).scalar_one_or_none()


async def send_once(*, key: str, user_id: uuid.UUID | None, to: str, template: str, prepare: Prepare) -> bool:
    """Send one email at most once per idempotency key. Returns False if it had already been sent.
    Raises ``EmailSendError`` on delivery failure (after recording it) so the event is retried."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        delivery_id = await _claim(session, key=key, user_id=user_id, to=to, template=template)
        if delivery_id is None:
            await session.rollback()
            logger.info("email_already_sent", template=template, idempotency_key=key)
            return False
        rendered = await prepare(session)
        await session.execute(
            update(EmailDelivery)
            .where(EmailDelivery.id == delivery_id)
            .values(subject=rendered.subject[:200])
        )
        await session.commit()

    message = mail.OutgoingEmail(
        to=to,
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
        headers={"X-BountyFlow-Template": template, "X-Entity-Ref-ID": key},
    )
    try:
        await mail.get_email_backend().send(message)
    except Exception as exc:
        error = str(exc)[:500] if isinstance(exc, mail.EmailSendError) else f"{type(exc).__name__}"
        async with sessionmaker() as session:
            await session.execute(
                update(EmailDelivery)
                .where(EmailDelivery.id == delivery_id)
                .values(status=EmailStatus.FAILED, last_error=error)
            )
            await session.commit()
        logger.warning("email_send_failed", template=template, idempotency_key=key, error=error)
        if isinstance(exc, mail.EmailSendError):
            raise
        raise mail.EmailSendError(error) from exc

    async with sessionmaker() as session:
        await session.execute(
            update(EmailDelivery)
            .where(EmailDelivery.id == delivery_id)
            .values(status=EmailStatus.SENT, sent_at=utcnow(), last_error=None)
        )
        await session.commit()
    logger.info("email_delivered", template=template, idempotency_key=key, user_id=str(user_id))
    return True


async def _load_user(session: AsyncSession, envelope: EventEnvelope) -> User | None:
    user = await session.get(User, uuid.UUID(str(envelope.payload["user_id"])))
    if user is None or not user.is_active:
        logger.info("email_skipped_no_active_user", event_type=envelope.event_type)
        return None
    return user


@on(CONSUMER, TOPICS, EventType.EMAIL_VERIFICATION_REQUESTED)
async def handle_verification_requested(session: AsyncSession, envelope: EventEnvelope) -> None:
    from app.modules.auth.service import issue_email_verification_token

    user = await _load_user(session, envelope)
    if user is None:
        return
    if user.email_verified_at is not None:
        logger.info("email_skipped_already_verified", user_id=str(user.id))
        return
    user_id, name, to = user.id, user.display_name, user.email

    async def prepare(tx: AsyncSession) -> mail.RenderedEmail:
        target = await tx.get(User, user_id)
        assert target is not None
        raw_token = await issue_email_verification_token(tx, target)
        return mail.render_verify_email(name, raw_token)

    await send_once(
        key=idempotency_key(envelope.event_id, mail.VERIFY_EMAIL),
        user_id=user_id,
        to=to,
        template=mail.VERIFY_EMAIL,
        prepare=prepare,
    )


@on(CONSUMER, TOPICS, EventType.PASSWORD_RESET_REQUESTED)
async def handle_password_reset_requested(session: AsyncSession, envelope: EventEnvelope) -> None:
    from app.modules.auth.service import issue_password_reset_token

    user = await _load_user(session, envelope)
    if user is None:
        return
    user_id, name, to = user.id, user.display_name, user.email

    async def prepare(tx: AsyncSession) -> mail.RenderedEmail:
        target = await tx.get(User, user_id)
        assert target is not None
        raw_token = await issue_password_reset_token(tx, target)
        return mail.render_password_reset(name, raw_token)

    await send_once(
        key=idempotency_key(envelope.event_id, mail.PASSWORD_RESET),
        user_id=user_id,
        to=to,
        template=mail.PASSWORD_RESET,
        prepare=prepare,
    )


def should_email_notification(
    user: User, preference: NotificationPreference | None, notification_type: NotificationType
) -> bool:
    """Only active users with a verified address who allow email for this type."""
    if not user.is_active or user.email_verified_at is None:
        return False
    email_enabled = preference.email_enabled if preference else prefs.DEFAULT_EMAIL_ENABLED
    return prefs.allows_email(email_enabled, preference.types if preference else None, notification_type)


@on(CONSUMER, TOPICS, EventType.NOTIFICATION_CREATED)
async def handle_notification_created(session: AsyncSession, envelope: EventEnvelope) -> None:
    notification = await session.get(Notification, uuid.UUID(str(envelope.payload["notification_id"])))
    if notification is None:
        return
    user = await session.get(User, notification.user_id)
    if user is None:
        return
    preference = await session.get(NotificationPreference, user.id)
    if not should_email_notification(user, preference, notification.notification_type):
        return
    rendered = mail.render_notification(
        recipient_name=user.display_name,
        notification_type=notification.notification_type,
        title=notification.title,
        message=notification.message,
        link=notification.link,
        payload=notification.payload,
    )

    async def prepare(_: AsyncSession) -> mail.RenderedEmail:
        return rendered

    await send_once(
        key=idempotency_key(envelope.event_id, mail.NOTIFICATION),
        user_id=user.id,
        to=user.email,
        template=mail.NOTIFICATION,
        prepare=prepare,
    )
