"""Notification use cases: idempotent creation (from domain events), inbox listing, read state, preferences."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.core.logging import get_logger
from app.core.schemas import Page, PageParams
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.notifications import preferences as prefs
from app.modules.notifications import repository as repo
from app.modules.notifications.models import Notification, NotificationType
from app.modules.notifications.schemas import (
    NotificationOut,
    NotificationPage,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
    TypePreference,
)
from app.modules.users.models import User

logger = get_logger(__name__)

TITLE_MAX = 200
LINK_MAX = 300


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


async def create_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    notification_type: NotificationType,
    title: str,
    message: str,
    link: str | None = None,
    payload: dict[str, Any] | None = None,
    source_event_id: uuid.UUID | None = None,
) -> Notification | None:
    """Create an in-app notification unless the recipient disabled this type in-app, or the same source
    event already produced one for them (redelivery). Stages ``notification.created`` in the outbox so the
    email worker can decide on email delivery. Does not commit: the caller owns the transaction."""
    preference = await repo.get_preference(session, user_id)
    if not prefs.allows_in_app(preference.types if preference else None, notification_type):
        return None
    notification = await repo.insert_notification(
        session,
        user_id=user_id,
        notification_type=notification_type,
        title=_clip(title, TITLE_MAX),
        message=message,
        link=link[:LINK_MAX] if link else None,
        payload=payload or {},
        source_event_id=source_event_id,
    )
    if notification is None:
        logger.info(
            "notification_duplicate_skipped", user_id=str(user_id), source_event_id=str(source_event_id)
        )
        return None
    add_event(
        session,
        event_type=EventType.NOTIFICATION_CREATED,
        aggregate_type="notification",
        aggregate_id=notification.id,
        payload={
            "notification_id": notification.id,
            "user_id": user_id,
            "notification_type": notification_type.value,
        },
    )
    return notification


async def list_notifications(
    session: AsyncSession, user: User, params: PageParams, *, unread_only: bool = False
) -> NotificationPage:
    rows, total = await repo.list_for_user(
        session, user.id, unread_only=unread_only, offset=params.offset, limit=params.page_size
    )
    page = Page[NotificationOut].build([NotificationOut.model_validate(n) for n in rows], total, params)
    unread = total if unread_only else await repo.unread_count(session, user.id)
    return NotificationPage(
        items=page.items,
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
        unread_count=unread,
    )


async def mark_read(session: AsyncSession, user: User, notification_id: uuid.UUID) -> None:
    if not await repo.mark_read(session, user.id, notification_id, utcnow()):
        raise NotFound("Notification not found.")
    await session.commit()


async def mark_all_read(session: AsyncSession, user: User) -> int:
    count = await repo.mark_all_read(session, user.id, utcnow())
    await session.commit()
    return count


def _preferences_out(email_enabled: bool, stored: dict[str, Any] | None) -> NotificationPreferencesOut:
    merged = prefs.merge_preferences(stored)
    return NotificationPreferencesOut(
        email_enabled=email_enabled,
        types={NotificationType(k): TypePreference(**v) for k, v in merged.items()},
    )


async def get_preferences(session: AsyncSession, user: User) -> NotificationPreferencesOut:
    preference = await repo.get_preference(session, user.id)
    if preference is None:
        return _preferences_out(prefs.DEFAULT_EMAIL_ENABLED, None)
    return _preferences_out(preference.email_enabled, preference.types)


async def update_preferences(
    session: AsyncSession, user: User, data: NotificationPreferencesUpdate
) -> NotificationPreferencesOut:
    preference = await repo.get_preference(session, user.id)
    email_enabled = preference.email_enabled if preference else prefs.DEFAULT_EMAIL_ENABLED
    stored = dict(preference.types) if preference else {}
    if data.email_enabled is not None:
        email_enabled = data.email_enabled
    if data.types:
        changes = {t.value: v.model_dump() for t, v in data.types.items()}
        stored = prefs.apply_update(stored, changes)
    await repo.upsert_preference(session, user.id, email_enabled=email_enabled, types=stored)
    await session.commit()
    return _preferences_out(email_enabled, stored)
