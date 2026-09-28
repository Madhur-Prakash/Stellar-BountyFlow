"""Idempotent event processing shared by the Kafka consumers and the in-process dispatcher."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import insert

from app.core.logging import bind_context, get_logger, unbind_context
from app.db.session import get_sessionmaker
from app.messaging.events import EventEnvelope
from app.messaging.models import ProcessedEvent
from app.messaging.registry import Consumer
from app.messaging.schemas import UnknownEventType, validate_payload

logger = get_logger(__name__)


class MalformedEvent(ValueError):
    """Permanent failure: the message can never be processed and goes straight to the DLQ."""


def parse_envelope(raw: dict[str, Any]) -> EventEnvelope:
    try:
        envelope = EventEnvelope.model_validate(raw)
        envelope.payload = validate_payload(envelope.event_type, envelope.payload)
    except (ValidationError, UnknownEventType, TypeError) as exc:
        raise MalformedEvent(str(exc)) from exc
    return envelope


async def process_event(consumer: Consumer, envelope: EventEnvelope) -> bool:
    """Runs the consumer's handler inside one DB transaction together with the processed-event marker, so
    a handler's effects and its idempotency record commit atomically. Returns False for duplicates."""
    handler = consumer.handler_for(envelope.event_type)
    if handler is None:
        return False
    async with get_sessionmaker()() as session:
        result = await session.execute(
            insert(ProcessedEvent)
            .values(consumer=consumer.name, event_id=envelope.event_id)
            .on_conflict_do_nothing()
            .returning(ProcessedEvent.event_id)
        )
        if result.scalar_one_or_none() is None:
            await session.rollback()
            logger.info("event_duplicate_skipped", consumer=consumer.name, event_id=str(envelope.event_id))
            return False
        bind_context(correlation_id=envelope.correlation_id, event_type=envelope.event_type)
        try:
            await handler(session, envelope)
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            unbind_context("event_type")
    return True
