"""Compliance event handlers.

* ``email-worker``: the "data export ready" and "deletion scheduled" emails. They answer the user's own request,
  so they are sent regardless of notification preferences (like password reset emails), exactly once per event.
* ``compliance-worker``: records which legal versions a new account accepted when it signed up.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.messaging.events import EventEnvelope, EventType, Topics
from app.messaging.registry import on
from app.modules.compliance import legal
from app.modules.notifications import email as mail
from app.modules.notifications.email_handlers import TOPICS as EMAIL_TOPICS
from app.modules.notifications.email_handlers import idempotency_key, send_once
from app.modules.users.models import User

logger = get_logger(__name__)

DATA_EXPORT_READY = "data_export_ready"
ACCOUNT_DELETION_SCHEDULED = "account_deletion_scheduled"
PRIVACY_PATH = "/app/privacy"
CONSUMER = "compliance-worker"


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %B %Y, %H:%M UTC")
    except ValueError:
        return iso


def render_export_ready(recipient_name: str, expires_at: str) -> mail.RenderedEmail:
    settings = get_settings()
    return mail.render(
        DATA_EXPORT_READY,
        f"Your {settings.app_name} data export is ready",
        {
            "recipient_name": recipient_name,
            "expires_at": _when(expires_at),
            "action_url": mail.frontend_url(PRIVACY_PATH, settings=settings),
            "action_label": "Download your data",
        },
        settings,
    )


def render_deletion_scheduled(recipient_name: str, scheduled_for: str) -> mail.RenderedEmail:
    settings = get_settings()
    return mail.render(
        ACCOUNT_DELETION_SCHEDULED,
        f"Your {settings.app_name} account is scheduled for deletion",
        {
            "recipient_name": recipient_name,
            "scheduled_for": _when(scheduled_for),
            "action_url": mail.frontend_url(PRIVACY_PATH, settings=settings),
            "action_label": "Review or cancel",
        },
        settings,
    )


async def _send(envelope: EventEnvelope, session: AsyncSession, template: str, rendered_for: str) -> None:
    user = await session.get(User, uuid.UUID(str(envelope.payload["user_id"])))
    if user is None or not user.is_active:
        logger.info("email_skipped_no_active_user", event_type=envelope.event_type)
        return
    if template == DATA_EXPORT_READY:
        rendered = render_export_ready(user.display_name, rendered_for)
    else:
        rendered = render_deletion_scheduled(user.display_name, rendered_for)

    async def prepare(_: AsyncSession) -> mail.RenderedEmail:
        return rendered

    await send_once(
        key=idempotency_key(envelope.event_id, template),
        user_id=user.id,
        to=user.email,
        template=template,
        prepare=prepare,
    )


@on("email-worker", EMAIL_TOPICS, EventType.DATA_EXPORT_READY)
async def handle_export_ready(session: AsyncSession, envelope: EventEnvelope) -> None:
    await _send(envelope, session, DATA_EXPORT_READY, str(envelope.payload["expires_at"]))


@on("email-worker", EMAIL_TOPICS, EventType.ACCOUNT_DELETION_REQUESTED)
async def handle_deletion_requested(session: AsyncSession, envelope: EventEnvelope) -> None:
    await _send(envelope, session, ACCOUNT_DELETION_SCHEDULED, str(envelope.payload["scheduled_for"]))


@on(CONSUMER, [Topics.ANALYTICS], EventType.USER_REGISTERED)
async def handle_user_registered(session: AsyncSession, envelope: EventEnvelope) -> None:
    user = await session.get(User, uuid.UUID(str(envelope.payload["user_id"])))
    if user is None:
        return
    # The versions in effect when the account was created (database time, like the version dates).
    recorded = await legal.record_registration(session, user.id, user.created_at)
    if recorded:
        logger.info("legal_acceptance_recorded", source="registration", documents=recorded)
