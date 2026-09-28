"""Notifications end to end against PostgreSQL: idempotent creation, handler dispatch, inbox, preferences,
and exactly-once email delivery."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.core.schemas import PageParams
from app.messaging.events import EventEnvelope, EventType
from app.messaging.models import OutboxEvent
from app.messaging.processing import process_event
from app.messaging.registry import all_consumers
from app.messaging.schemas import validate_payload
from app.modules.auth.models import EmailVerificationToken
from app.modules.notifications import email_handlers
from app.modules.notifications import service as notifications
from app.modules.notifications.email import EmailSendError
from app.modules.notifications.models import EmailDelivery, EmailStatus, Notification, NotificationType
from app.modules.notifications.schemas import NotificationPreferencesUpdate, TypePreferenceUpdate
from tests.conftest import CapturingEmailBackend
from tests.integration.factories import make_bounty, make_user

pytestmark = pytest.mark.integration


def consumer(name: str):  # type: ignore[no-untyped-def]
    return next(c for c in all_consumers() if c.name == name)


async def count(session: AsyncSession, model: type, *where: object) -> int:
    return int(await session.scalar(select(func.count()).select_from(model).where(*where)) or 0)


async def test_create_notification_is_idempotent_and_stages_outbox_event(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    event_id = uuid.uuid4()
    kwargs = {
        "user_id": user.id,
        "notification_type": NotificationType.SYSTEM,
        "title": "Hello",
        "message": "World",
        "link": "/app",
        "source_event_id": event_id,
    }
    first = await notifications.create_notification(db_session, **kwargs)
    second = await notifications.create_notification(db_session, **kwargs)
    await db_session.commit()
    assert first is not None
    assert second is None
    assert await count(db_session, Notification, Notification.user_id == user.id) == 1
    assert await count(db_session, OutboxEvent, OutboxEvent.event_type == EventType.NOTIFICATION_CREATED) == 1


async def test_in_app_preference_suppresses_notification(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    await notifications.update_preferences(
        db_session,
        user,
        NotificationPreferencesUpdate(types={NotificationType.SYSTEM: TypePreferenceUpdate(in_app=False)}),
    )
    created = await notifications.create_notification(
        db_session, user_id=user.id, notification_type=NotificationType.SYSTEM, title="t", message="m"
    )
    assert created is None
    prefs = await notifications.get_preferences(db_session, user)
    assert prefs.types[NotificationType.SYSTEM].in_app is False
    assert prefs.types[NotificationType.PAYMENT_CONFIRMED].email is True


async def test_notification_worker_handles_event_once(db: object, db_session: AsyncSession) -> None:
    requester = await make_user(db_session)
    contributor = await make_user(db_session)
    bounty = await make_bounty(db_session, requester)
    await db_session.commit()
    env = EventEnvelope(
        event_type=EventType.APPLICATION_CREATED,
        aggregate_type="application",
        aggregate_id=uuid.uuid4(),
        actor_id=contributor.id,
        payload=validate_payload(
            EventType.APPLICATION_CREATED,
            {
                "application_id": uuid.uuid4(),
                "bounty_id": bounty.id,
                "requester_id": requester.id,
                "contributor_id": contributor.id,
                "title": bounty.title,
                "status": "PENDING",
            },
        ),
    )
    worker = consumer("notification-worker")
    assert await process_event(worker, env) is True
    assert await process_event(worker, env) is False  # redelivery is a no-op
    rows = (await db_session.scalars(select(Notification))).all()
    assert [(n.user_id, n.notification_type) for n in rows] == [
        (requester.id, NotificationType.APPLICATION_RECEIVED)
    ]
    assert rows[0].source_event_id == env.event_id


async def test_inbox_listing_and_read_state(db_session: AsyncSession) -> None:
    user = await make_user(db_session)
    other = await make_user(db_session)
    for i in range(3):
        await notifications.create_notification(
            db_session, user_id=user.id, notification_type=NotificationType.SYSTEM, title=f"n{i}", message="m"
        )
    await db_session.commit()
    page = await notifications.list_notifications(db_session, user, PageParams(page=1, page_size=2))
    assert page.total == 3
    assert page.pages == 2
    assert len(page.items) == 2
    assert page.unread_count == 3

    await notifications.mark_read(db_session, user, page.items[0].id)
    unread = await notifications.list_notifications(db_session, user, PageParams(), unread_only=True)
    assert unread.total == 2
    assert unread.unread_count == 2

    with pytest.raises(NotFound):
        await notifications.mark_read(db_session, other, page.items[1].id)

    assert await notifications.mark_all_read(db_session, user) == 2
    assert (await notifications.list_notifications(db_session, user, PageParams())).unread_count == 0


async def test_verification_email_sent_exactly_once(
    db: object, db_session: AsyncSession, outbox_mail: CapturingEmailBackend
) -> None:
    user = await make_user(db_session, verified=False)
    await db_session.commit()
    env = EventEnvelope(
        event_type=EventType.EMAIL_VERIFICATION_REQUESTED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"user_id": str(user.id)},
    )
    await email_handlers.handle_verification_requested(db_session, env)
    await email_handlers.handle_verification_requested(db_session, env)  # redelivery bypassing the marker
    assert len(outbox_mail.sent) == 1
    message = outbox_mail.sent[0]
    assert message.to == user.email
    assert "/verify-email?token=" in message.text
    delivery = await db_session.scalar(select(EmailDelivery))
    assert delivery is not None
    assert delivery.status == EmailStatus.SENT
    assert delivery.attempts == 1
    assert delivery.idempotency_key == f"{env.event_id}:verify_email"
    assert await count(db_session, EmailVerificationToken, EmailVerificationToken.user_id == user.id) == 1


async def test_email_failure_is_recorded_and_retried(
    db: object, db_session: AsyncSession, outbox_mail: CapturingEmailBackend
) -> None:
    user = await make_user(db_session, verified=False)
    await db_session.commit()
    env = EventEnvelope(
        event_type=EventType.PASSWORD_RESET_REQUESTED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"user_id": str(user.id)},
    )
    outbox_mail.fail_next = 1
    with pytest.raises(EmailSendError):
        await email_handlers.handle_password_reset_requested(db_session, env)
    delivery = await db_session.scalar(select(EmailDelivery))
    assert delivery is not None
    assert delivery.status == EmailStatus.FAILED
    assert "simulated SMTP outage" in (delivery.last_error or "")

    await email_handlers.handle_password_reset_requested(db_session, env)
    await db_session.refresh(delivery)
    assert delivery.status == EmailStatus.SENT
    assert delivery.attempts == 2
    assert len(outbox_mail.sent) == 1
    assert "/reset-password?token=" in outbox_mail.sent[0].text


async def test_verified_user_already_verified_gets_no_verification_email(
    db: object, db_session: AsyncSession, outbox_mail: CapturingEmailBackend
) -> None:
    user = await make_user(db_session, verified=True)
    await db_session.commit()
    env = EventEnvelope(
        event_type=EventType.EMAIL_VERIFICATION_REQUESTED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"user_id": str(user.id)},
    )
    await email_handlers.handle_verification_requested(db_session, env)
    assert outbox_mail.sent == []


async def test_notification_email_respects_verification_and_preferences(
    db: object, db_session: AsyncSession, outbox_mail: CapturingEmailBackend
) -> None:
    verified = await make_user(db_session, verified=True)
    unverified = await make_user(db_session, verified=False)
    opted_out = await make_user(db_session, verified=True)
    await notifications.update_preferences(
        db_session, opted_out, NotificationPreferencesUpdate(email_enabled=False)
    )

    async def notify(user_id: uuid.UUID, ntype: NotificationType) -> EventEnvelope:
        n = await notifications.create_notification(
            db_session,
            user_id=user_id,
            notification_type=ntype,
            title="Payment received",
            message="You got paid",
            link="/app/payments",
            payload={"amount": "5.0000000"},
        )
        assert n is not None
        await db_session.commit()
        return EventEnvelope(
            event_type=EventType.NOTIFICATION_CREATED,
            aggregate_type="notification",
            aggregate_id=n.id,
            payload={"notification_id": str(n.id), "user_id": str(user_id), "notification_type": ntype.value},
        )

    for user in (verified, unverified, opted_out):
        await email_handlers.handle_notification_created(
            db_session, await notify(user.id, NotificationType.PAYMENT_CONFIRMED)
        )
    # A type that does not email by default.
    await email_handlers.handle_notification_created(
        db_session, await notify(verified.id, NotificationType.BOUNTY_PUBLISHED)
    )

    assert [m.to for m in outbox_mail.sent] == [verified.email]
    assert "/app/payments" in outbox_mail.sent[0].html
