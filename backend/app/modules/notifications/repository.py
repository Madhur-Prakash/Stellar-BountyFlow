"""Database access for notifications and notification preferences."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification, NotificationPreference, NotificationType


async def get_preference(session: AsyncSession, user_id: uuid.UUID) -> NotificationPreference | None:
    return await session.get(NotificationPreference, user_id)


async def insert_notification(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    notification_type: NotificationType,
    title: str,
    message: str,
    link: str | None,
    payload: dict[str, Any],
    source_event_id: uuid.UUID | None,
) -> Notification | None:
    """INSERT ... ON CONFLICT DO NOTHING on (user_id, source_event_id). Returns None for a duplicate."""
    stmt = (
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
            payload=payload,
            source_event_id=source_event_id,
        )
        .on_conflict_do_nothing(constraint="uq_bountyflow_notifications_user_event")
        .returning(Notification)
    )
    return (await session.scalars(stmt)).first()


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, unread_only: bool, offset: int, limit: int
) -> tuple[list[Notification], int]:
    conditions = [Notification.user_id == user_id]
    if unread_only:
        conditions.append(Notification.read_at.is_(None))
    total = await session.scalar(select(func.count(Notification.id)).where(*conditions)) or 0
    rows = await session.scalars(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows.all()), total


async def unread_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id, Notification.read_at.is_(None)
            )
        )
        or 0
    )


async def mark_read(
    session: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID, now: datetime
) -> bool:
    """Marks one notification read. Returns False if it does not exist or belongs to someone else."""
    notification = await session.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    if notification is None:
        return False
    if notification.read_at is None:
        notification.read_at = now
    return True


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def upsert_preference(
    session: AsyncSession, user_id: uuid.UUID, *, email_enabled: bool, types: dict[str, Any]
) -> None:
    stmt = insert(NotificationPreference).values(user_id=user_id, email_enabled=email_enabled, types=types)
    stmt = stmt.on_conflict_do_update(
        index_elements=[NotificationPreference.user_id],
        set_={
            "email_enabled": stmt.excluded.email_enabled,
            "types": stmt.excluded.types,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
