"""Consumer retry policy, backoff, DLQ decisions, and the Kafka record handling path (with fakes)."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.exceptions import NotFound, ServiceUnavailable
from app.messaging.events import EventEnvelope, EventType
from app.messaging.processing import MalformedEvent
from app.messaging.registry import Consumer
from worker import consumer as consumer_module
from worker.consumer import ConsumerRunner, decode_record, dlq_payload, group_id
from worker.retry import (
    Decision,
    Outcome,
    backoff_delay,
    decide,
    dlq_headers,
    is_permanent,
    run_with_retries,
)

# --- Pure policy --------------------------------------------------------------------------------------


def test_backoff_grows_exponentially_with_bounded_jitter() -> None:
    assert backoff_delay(1, rng=lambda: 0.0) == 0.25
    assert backoff_delay(1, rng=lambda: 1.0) == 0.5
    assert backoff_delay(3, rng=lambda: 1.0) == 2.0
    assert backoff_delay(4, rng=lambda: 0.5) == pytest.approx(3.0)


def test_backoff_is_capped() -> None:
    assert backoff_delay(50, rng=lambda: 1.0) == 30.0
    assert 15.0 <= backoff_delay(50) <= 30.0


def test_permanent_errors() -> None:
    assert is_permanent(MalformedEvent("bad"))
    assert is_permanent(NotFound("gone"))
    assert not is_permanent(ServiceUnavailable("down"))
    assert not is_permanent(ConnectionError("db"))


def test_decide_retries_transient_until_exhausted() -> None:
    err = ConnectionError("db down")
    assert decide(err, 1, 3) is Decision.RETRY
    assert decide(err, 3, 3) is Decision.RETRY
    assert decide(err, 4, 3) is Decision.DEAD_LETTER
    assert decide(err, 1, 0) is Decision.DEAD_LETTER


def test_decide_dead_letters_permanent_immediately() -> None:
    assert decide(MalformedEvent("x"), 1, 10) is Decision.DEAD_LETTER
    assert decide(NotFound("x"), 1, 10) is Decision.DEAD_LETTER


def test_dlq_headers_carry_error_metadata() -> None:
    headers = dict(
        dlq_headers(
            consumer="c", topic="bounty.events", partition=2, offset=41, error=ValueError("boom"), attempts=6
        )
    )
    assert headers["x-consumer"] == b"c"
    assert headers["x-original-topic"] == b"bounty.events"
    assert headers["x-original-partition"] == b"2"
    assert headers["x-original-offset"] == b"41"
    assert headers["x-error-type"] == b"ValueError"
    assert headers["x-error-message"] == b"boom"
    assert headers["x-attempts"] == b"6"
    assert headers["x-permanent"] == b"false"


# --- run_with_retries ------------------------------------------------------------------------------


async def no_sleep(delay: float, stop: asyncio.Event | None) -> bool:
    return False


async def test_run_with_retries_succeeds_after_transient_failures() -> None:
    calls = 0
    delays: list[float] = []

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("transient")

    result = await run_with_retries(
        flaky, max_retries=5, sleep=no_sleep, rng=lambda: 1.0, on_retry=lambda e, a, d: delays.append(d)
    )
    assert result.outcome is Outcome.SUCCEEDED
    assert result.attempts == 3
    assert delays == [0.5, 1.0]


async def test_run_with_retries_dead_letters_after_max_retries() -> None:
    calls = 0

    async def always_fails() -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("down")

    result = await run_with_retries(always_fails, max_retries=2, sleep=no_sleep)
    assert result.outcome is Outcome.DEAD_LETTERED
    assert calls == 3
    assert isinstance(result.error, ConnectionError)


async def test_run_with_retries_aborts_on_shutdown() -> None:
    async def stopping_sleep(delay: float, stop: asyncio.Event | None) -> bool:
        return True

    async def fails() -> None:
        raise ConnectionError("down")

    result = await run_with_retries(fails, max_retries=5, sleep=stopping_sleep)
    assert result.outcome is Outcome.ABORTED
    assert result.attempts == 1


async def test_interruptible_sleep_returns_immediately_when_stopped() -> None:
    from worker.retry import interruptible_sleep

    stop = asyncio.Event()
    stop.set()
    assert await asyncio.wait_for(interruptible_sleep(60, stop), timeout=1) is True
    assert await interruptible_sleep(0.01, asyncio.Event()) is False


# --- Record decoding ------------------------------------------------------------------------------------


def test_decode_record_rejects_non_objects() -> None:
    assert decode_record(b'{"a": 1}') == {"a": 1}
    for bad in (None, b"not json", b"[1,2]", b"\xff\xfe"):
        with pytest.raises(MalformedEvent):
            decode_record(bad)


def test_dlq_payload_preserves_original() -> None:
    assert dlq_payload(b'{"event_id": "x"}') == {"event_id": "x"}
    assert dlq_payload(b"garbage") == {"raw": "garbage"}


# --- ConsumerRunner.handle_record with fakes ------------------------------------------------------------


@dataclass
class FakeRecord:
    value: bytes | None
    topic: str = "application.events"
    partition: int = 0
    offset: int = 7
    key: bytes | None = b"agg"


@dataclass
class FakeProducer:
    sent: list[dict[str, Any]] = field(default_factory=list)

    async def send_and_wait(
        self, topic: str, value: Any = None, key: Any = None, headers: Any = None
    ) -> None:
        self.sent.append({"topic": topic, "value": value, "key": key, "headers": dict(headers or [])})


class FakeSettings:
    kafka_consumer_group = "bf"
    worker_max_retries = 2


def valid_record() -> FakeRecord:
    env = EventEnvelope(
        event_type=EventType.APPLICATION_CREATED,
        aggregate_type="application",
        aggregate_id=uuid.uuid4(),
        payload={
            "application_id": str(uuid.uuid4()),
            "bounty_id": str(uuid.uuid4()),
            "requester_id": str(uuid.uuid4()),
            "contributor_id": str(uuid.uuid4()),
            "title": "T",
            "status": "PENDING",
        },
    )
    return FakeRecord(json.dumps(env.model_dump(mode="json")).encode())


@pytest.fixture
def runner() -> tuple[ConsumerRunner, FakeProducer]:
    producer = FakeProducer()
    c = Consumer(name="notification-worker", topics=["application.events"])
    r = ConsumerRunner(c, producer, asyncio.Event(), settings=FakeSettings())  # type: ignore[arg-type]
    return r, producer


def test_group_id_is_per_consumer() -> None:
    c = Consumer(name="email-worker", topics=[])
    assert group_id(FakeSettings(), c) == "bf.email-worker"  # type: ignore[arg-type]


async def test_malformed_record_goes_straight_to_dlq(runner: tuple[ConsumerRunner, FakeProducer]) -> None:
    r, producer = runner
    assert await r.handle_record(FakeRecord(b"{not json"))  # type: ignore[arg-type]
    [dead] = producer.sent
    assert dead["topic"] == "application.events.dlq"
    assert dead["value"] == {"raw": "{not json"}
    assert dead["headers"]["x-permanent"] == b"true"


async def test_exhausted_record_is_dead_lettered(
    runner: tuple[ConsumerRunner, FakeProducer], monkeypatch: pytest.MonkeyPatch
) -> None:
    r, producer = runner
    calls = 0

    async def failing(consumer: Consumer, envelope: EventEnvelope) -> bool:
        nonlocal calls
        calls += 1
        raise ConnectionError("db down")

    async def fast_sleep(delay: float, stop: asyncio.Event | None) -> bool:
        return False

    monkeypatch.setattr(consumer_module, "process_event", failing)
    import worker.retry as retry_module

    original = retry_module.run_with_retries

    async def patched(fn: Any, **kwargs: Any) -> Any:
        kwargs["sleep"] = fast_sleep
        return await original(fn, **kwargs)

    monkeypatch.setattr(consumer_module, "run_with_retries", patched)
    record = valid_record()
    assert await r.handle_record(record)  # type: ignore[arg-type]
    assert calls == 3  # first attempt + 2 retries
    [dead] = producer.sent
    assert dead["headers"]["x-attempts"] == b"3"
    assert dead["headers"]["x-error-type"] == b"ConnectionError"
    assert dead["value"]["event_type"] == EventType.APPLICATION_CREATED


async def test_successful_record_is_not_dead_lettered(
    runner: tuple[ConsumerRunner, FakeProducer], monkeypatch: pytest.MonkeyPatch
) -> None:
    r, producer = runner
    seen: list[str] = []

    async def ok(consumer: Consumer, envelope: EventEnvelope) -> bool:
        seen.append(envelope.event_type)
        return True

    monkeypatch.setattr(consumer_module, "process_event", ok)
    assert await r.handle_record(valid_record())  # type: ignore[arg-type]
    assert seen == [EventType.APPLICATION_CREATED]
    assert producer.sent == []
