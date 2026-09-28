"""Transactional outbox: events are inserted in the same DB transaction as the state change they describe,
then relayed to Kafka by the worker. This guarantees no event is lost between commit and publish."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_context, get_logger
from app.core.security import utcnow
from app.messaging.events import EventEnvelope, topic_for
from app.messaging.models import OutboxEvent
from app.messaging.schemas import validate_payload

logger = get_logger(__name__)


def _correlation_id() -> str | None:
    ctx = get_context()
    value = ctx.get("correlation_id")
    return str(value) if value else None


def add_event(
    session: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: dict[str, Any],
    actor_id: uuid.UUID | None = None,
    topic: str | None = None,
) -> EventEnvelope:
    """Stage a domain event. The caller's transaction commit makes it durable."""
    envelope = EventEnvelope(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor_id=actor_id,
        correlation_id=_correlation_id(),
        payload=validate_payload(event_type, payload),
    )
    session.add(
        OutboxEvent(
            id=envelope.event_id,
            topic=topic or topic_for(event_type),
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=envelope.model_dump(mode="json"),
        )
    )
    return envelope


Publisher = Callable[[str, str, dict[str, Any]], Awaitable[None]]  # (topic, key, envelope)


async def relay_batch(
    session: AsyncSession, publish: Publisher, batch_size: int = 100, max_attempts: int = 25
) -> int:
    """Publish one batch of unpublished events. Row locks (SKIP LOCKED) let several relays run safely.
    Delivery is at-least-once: if publishing succeeds but the commit fails, the event is re-sent and
    consumers deduplicate on event_id."""
    rows = (
        await session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    ).all()
    published = 0
    for row in rows:
        try:
            await publish(row.topic, str(row.aggregate_id), row.payload)
        except Exception as exc:
            row.retry_count += 1
            row.last_error = str(exc)[:500]
            if row.retry_count >= max_attempts:
                # Safety valve: never let one poison event block the outbox forever. The row keeps its error for
                # inspection and can be re-queued by clearing published_at.
                row.published_at = utcnow()
                logger.error(
                    "outbox_event_dead_lettered",
                    event_id=str(row.id),
                    event_type=row.event_type,
                    attempts=row.retry_count,
                    error=str(exc)[:300],
                )
                continue
            logger.warning(
                "outbox_publish_failed", event_id=str(row.id), attempt=row.retry_count, error=str(exc)
            )
            break  # preserve ordering; retry this batch later
        row.published_at = utcnow()
        published += 1
    await session.commit()
    return published


async def mark_all_published(session: AsyncSession) -> None:  # pragma: no cover - maintenance helper
    await session.execute(
        update(OutboxEvent).where(OutboxEvent.published_at.is_(None)).values(published_at=utcnow())
    )
    await session.commit()
