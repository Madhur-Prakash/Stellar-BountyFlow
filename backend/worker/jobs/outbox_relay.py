"""Transactional outbox relay: moves committed events from ``outbox_events`` to Kafka, or, when Kafka is
disabled (local development), dispatches them in-process to every subscribed consumer."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from aiokafka import AIOKafkaProducer

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.messaging.outbox import Publisher, relay_batch
from app.messaging.processing import MalformedEvent, parse_envelope, process_event
from app.messaging.registry import Consumer
from worker.retry import Outcome, backoff_delay, interruptible_sleep, run_with_retries

logger = get_logger(__name__)

IN_PROCESS_MAX_DELAY = 2.0  # keep in-process retries short: they block the relay loop


class RelayAborted(Exception):
    """Shutdown interrupted in-process dispatch; the outbox row stays unpublished and is retried."""


def kafka_publisher(producer: AIOKafkaProducer, settings: Settings | None = None) -> Publisher:
    settings = settings or get_settings()

    async def publish(topic: str, key: str, envelope: dict[str, Any]) -> None:
        await producer.send_and_wait(settings.topic(topic), value=envelope, key=key)

    return publish


class InProcessDispatcher:
    """Publisher used without Kafka: runs ``process_event`` for every consumer subscribed to the topic, with the
    same idempotency guarantees as the Kafka path. Exhausted events are logged as dead-lettered (there is no
    DLQ topic without Kafka) so one poisonous event cannot block the outbox."""

    def __init__(
        self,
        consumers: Sequence[Consumer],
        stop: asyncio.Event | None = None,
        *,
        max_retries: int | None = None,
    ) -> None:
        self.consumers = list(consumers)
        self.stop = stop
        self.max_retries = get_settings().worker_max_retries if max_retries is None else max_retries

    def subscribers(self, topic: str, event_type: str) -> list[Consumer]:
        return [c for c in self.consumers if topic in c.topics and c.handler_for(event_type) is not None]

    async def __call__(self, topic: str, key: str, envelope: dict[str, Any]) -> None:
        try:
            event = parse_envelope(envelope)
        except MalformedEvent as exc:
            logger.error("event_malformed", topic=topic, error=str(exc)[:300], dispatch="in_process")
            return
        for consumer in self.subscribers(topic, event.event_type):
            result = await run_with_retries(
                lambda consumer=consumer: process_event(consumer, event),  # type: ignore[misc]
                max_retries=self.max_retries,
                stop=self.stop,
                cap=IN_PROCESS_MAX_DELAY,
            )
            if result.outcome is Outcome.ABORTED:
                raise RelayAborted(f"dispatch of {event.event_id} interrupted by shutdown")
            if result.outcome is Outcome.DEAD_LETTERED:
                logger.error(
                    "event_dead_lettered",
                    consumer=consumer.name,
                    event_id=str(event.event_id),
                    event_type=event.event_type,
                    attempts=result.attempts,
                    dispatch="in_process",
                    error_type=type(result.error).__name__,
                    error=str(result.error)[:300],
                )


async def relay_once(publisher: Publisher, batch_size: int) -> int:
    async with get_sessionmaker()() as session:
        return await relay_batch(session, publisher, batch_size)


async def run_outbox_relay(
    publisher: Publisher,
    stop: asyncio.Event,
    *,
    interval: float | None = None,
    batch_size: int | None = None,
) -> None:
    settings = get_settings()
    interval = settings.outbox_poll_interval_seconds if interval is None else interval
    batch_size = settings.outbox_batch_size if batch_size is None else batch_size
    failures = 0
    logger.info("outbox_relay_started", interval=interval, batch_size=batch_size)
    while not stop.is_set():
        try:
            published = await relay_once(publisher, batch_size)
            failures = 0
        except Exception as exc:
            failures += 1
            delay = backoff_delay(failures)
            logger.warning("outbox_relay_failed", error=str(exc)[:300], retry_in=round(delay, 2))
            await interruptible_sleep(delay, stop)
            continue
        if published:
            logger.debug("outbox_relayed", count=published)
        if published >= batch_size:
            continue  # a full batch: more events are probably waiting
        await interruptible_sleep(interval, stop)
    logger.info("outbox_relay_stopped")
