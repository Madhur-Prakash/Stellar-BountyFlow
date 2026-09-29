"""Kafka consumer loop for one registered event consumer (one consumer group per registry ``Consumer``).

Delivery is at-least-once: an offset is committed only after the event was processed or dead-lettered, and
``process_event`` deduplicates on ``(consumer, event_id)``. Malformed messages go straight to ``<topic>.dlq``;
handler failures are retried with bounded exponential backoff and dead-lettered once retries are exhausted.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, ConsumerRecord, TopicPartition
from aiokafka.errors import CommitFailedError, KafkaError

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.messaging.events import Topics
from app.messaging.kafka import create_consumer
from app.messaging.processing import MalformedEvent, parse_envelope, process_event
from app.messaging.registry import Consumer
from app.modules.ops.health import record_consumer_lag
from worker.retry import Outcome, backoff_delay, dlq_headers, interruptible_sleep, run_with_retries

logger = get_logger(__name__)

POLL_TIMEOUT_MS = 1000
MAX_POLL_RECORDS = 50
LAG_LOG_INTERVAL = 60.0


def group_id(settings: Settings, consumer: Consumer) -> str:
    return f"{settings.kafka_consumer_group}.{consumer.name}"


def decode_record(value: bytes | None) -> dict[str, Any]:
    """Raw Kafka value -> JSON object. Anything that is not a JSON object is malformed."""
    if value is None:
        raise MalformedEvent("Empty message")
    try:
        data = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedEvent(f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedEvent("Message is not a JSON object")
    return data


def dlq_payload(value: bytes | None) -> dict[str, Any]:
    """The original message for the DLQ: the JSON object itself when possible, else the raw text."""
    try:
        return decode_record(value)
    except MalformedEvent:
        return {"raw": (value or b"").decode("utf-8", errors="replace")}


class ConsumerRunner:
    def __init__(
        self,
        consumer: Consumer,
        producer: AIOKafkaProducer,
        stop: asyncio.Event,
        *,
        settings: Settings | None = None,
        consumer_factory: Callable[[str, list[str]], AIOKafkaConsumer] = create_consumer,
    ) -> None:
        self.consumer = consumer
        self.producer = producer
        self.stop = stop
        self.settings = settings or get_settings()
        self.consumer_factory = consumer_factory
        self._last_lag_log = 0.0

    async def run(self) -> None:
        gid = group_id(self.settings, self.consumer)
        kafka_consumer = self.consumer_factory(gid, self.consumer.topics)
        await kafka_consumer.start()
        logger.info(
            "consumer_started", consumer=self.consumer.name, group_id=gid, topics=self.consumer.topics
        )
        try:
            await self._loop(kafka_consumer)
        finally:
            try:
                await kafka_consumer.stop()
            except Exception as exc:
                logger.warning("consumer_stop_failed", consumer=self.consumer.name, error=str(exc))
            logger.info("consumer_stopped", consumer=self.consumer.name)

    async def _loop(self, kafka_consumer: AIOKafkaConsumer) -> None:
        while not self.stop.is_set():
            batches = await kafka_consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=MAX_POLL_RECORDS)
            for tp, records in batches.items():
                for record in records:
                    if self.stop.is_set():
                        return  # uncommitted records are redelivered after restart
                    if not await self.handle_record(record):
                        return
                    await self._commit(kafka_consumer, tp, record.offset + 1)
            await self._maybe_log_lag(kafka_consumer)

    async def handle_record(self, record: ConsumerRecord[Any, Any]) -> bool:
        """Process one record. Returns True when it may be committed (processed or dead-lettered)."""
        try:
            envelope = parse_envelope(decode_record(record.value))
        except MalformedEvent as exc:
            logger.error(
                "event_malformed",
                consumer=self.consumer.name,
                topic=record.topic,
                offset=record.offset,
                error=str(exc)[:300],
            )
            return await self.dead_letter(record, exc, attempts=1)

        def on_retry(exc: BaseException, attempt: int, delay: float) -> None:
            logger.warning(
                "event_retry_scheduled",
                consumer=self.consumer.name,
                event_id=str(envelope.event_id),
                event_type=envelope.event_type,
                attempt=attempt,
                delay_seconds=round(delay, 2),
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )

        result = await run_with_retries(
            lambda: process_event(self.consumer, envelope),
            max_retries=self.settings.worker_max_retries,
            stop=self.stop,
            on_retry=on_retry,
        )
        if result.outcome is Outcome.SUCCEEDED:
            return True
        if result.outcome is Outcome.ABORTED:
            return False
        assert result.error is not None
        logger.error(
            "event_dead_lettered",
            consumer=self.consumer.name,
            event_id=str(envelope.event_id),
            event_type=envelope.event_type,
            attempts=result.attempts,
            error_type=type(result.error).__name__,
            error=str(result.error)[:300],
        )
        return await self.dead_letter(record, result.error, attempts=result.attempts)

    async def dead_letter(
        self, record: ConsumerRecord[Any, Any], error: BaseException, *, attempts: int
    ) -> bool:
        """Publish the original message to ``<topic>.dlq`` with error metadata headers, retrying the publish
        until it succeeds. Returns False if shutdown interrupted it (the record is then not committed)."""
        topic = Topics.dlq(record.topic)  # record.topic already carries any configured prefix
        headers = dlq_headers(
            consumer=self.consumer.name,
            topic=record.topic,
            partition=record.partition,
            offset=record.offset,
            error=error,
            attempts=attempts,
        )
        attempt = 0
        while True:
            attempt += 1
            try:
                await self.producer.send_and_wait(
                    topic,
                    value=dlq_payload(record.value),
                    key=record.key.decode("utf-8", errors="replace") if record.key else None,
                    headers=headers,
                )
                return True
            except KafkaError as exc:
                delay = backoff_delay(attempt)
                logger.error(
                    "dlq_publish_failed",
                    consumer=self.consumer.name,
                    topic=topic,
                    error=str(exc),
                    retry_in=round(delay, 2),
                )
                if await interruptible_sleep(delay, self.stop):
                    return False

    async def _commit(self, kafka_consumer: AIOKafkaConsumer, tp: TopicPartition, offset: int) -> None:
        try:
            await kafka_consumer.commit({tp: offset})
        except CommitFailedError as exc:
            # The partition was rebalanced away; its new owner re-reads from the last commit (idempotent).
            logger.warning(
                "offset_commit_failed", consumer=self.consumer.name, partition=tp.partition, error=str(exc)
            )

    async def _maybe_log_lag(self, kafka_consumer: AIOKafkaConsumer) -> None:
        now = time.monotonic()
        if now - self._last_lag_log < LAG_LOG_INTERVAL:
            return
        self._last_lag_log = now
        assignment = list(kafka_consumer.assignment())
        if not assignment:
            return
        try:
            end_offsets = await kafka_consumer.end_offsets(assignment)
            lag: dict[str, int] = {}
            for tp in assignment:
                position = await kafka_consumer.position(tp)
                lag[f"{tp.topic}[{tp.partition}]"] = max(0, end_offsets.get(tp, position) - position)
        except KafkaError as exc:
            logger.warning("consumer_lag_unavailable", consumer=self.consumer.name, error=str(exc))
            return
        logger.info("consumer_lag", consumer=self.consumer.name, total_lag=sum(lag.values()), partitions=lag)
        await record_consumer_lag(self.consumer.name, lag)  # exported as bountyflow_kafka_consumer_lag
