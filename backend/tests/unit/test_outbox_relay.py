"""Outbox relay semantics with a fake publisher and session, and the in-process dispatcher."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.messaging.events import EventEnvelope, EventType, Topics
from app.messaging.models import OutboxEvent
from app.messaging.outbox import relay_batch
from app.messaging.registry import Consumer
from worker.jobs import outbox_relay
from worker.jobs.outbox_relay import InProcessDispatcher, RelayAborted, kafka_publisher


def outbox_row(event_type: str = EventType.USER_REGISTERED) -> OutboxEvent:
    user_id = uuid.uuid4()
    env = EventEnvelope(
        event_type=event_type, aggregate_type="user", aggregate_id=user_id, payload={"user_id": str(user_id)}
    )
    return OutboxEvent(
        id=env.event_id,
        topic=Topics.ANALYTICS,
        aggregate_type="user",
        aggregate_id=user_id,
        event_type=event_type,
        payload=env.model_dump(mode="json"),
        retry_count=0,
    )


class FakeResult:
    def __init__(self, rows: list[OutboxEvent]) -> None:
        self._rows = rows

    def all(self) -> list[OutboxEvent]:
        return self._rows


class FakeSession:
    def __init__(self, rows: list[OutboxEvent]) -> None:
        self.rows = rows
        self.commits = 0

    async def scalars(self, stmt: Any) -> FakeResult:
        return FakeResult(self.rows)

    async def commit(self) -> None:
        self.commits += 1


class FakePublisher:
    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail_on = fail_on

    async def __call__(self, topic: str, key: str, envelope: dict[str, Any]) -> None:
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            self.calls.append((topic, key, envelope))
            raise ConnectionError("broker unavailable")
        self.calls.append((topic, key, envelope))


async def test_relay_publishes_in_order_and_marks_published() -> None:
    rows = [outbox_row(), outbox_row(), outbox_row()]
    session = FakeSession(rows)
    publisher = FakePublisher()
    assert await relay_batch(session, publisher, batch_size=10) == 3  # type: ignore[arg-type]
    assert [c[2]["event_id"] for c in publisher.calls] == [str(r.id) for r in rows]
    assert all(c[1] == str(r.aggregate_id) for c, r in zip(publisher.calls, rows, strict=True))
    assert all(r.published_at is not None for r in rows)
    assert session.commits == 1


async def test_relay_stops_at_first_failure_and_records_error() -> None:
    rows = [outbox_row(), outbox_row(), outbox_row()]
    session = FakeSession(rows)
    publisher = FakePublisher(fail_on=1)
    assert await relay_batch(session, publisher, batch_size=10) == 1  # type: ignore[arg-type]
    assert rows[0].published_at is not None
    assert rows[1].published_at is None
    assert rows[1].retry_count == 1
    assert "broker unavailable" in (rows[1].last_error or "")
    assert rows[2].published_at is None
    assert rows[2].retry_count == 0
    assert session.commits == 1


async def test_kafka_publisher_applies_topic_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, Any, Any]] = []

    class Producer:
        async def send_and_wait(self, topic: str, value: Any = None, key: Any = None) -> None:
            sent.append((topic, value, key))

    class Settings:
        def topic(self, name: str) -> str:
            return f"staging.{name}"

    publish = kafka_publisher(Producer(), Settings())  # type: ignore[arg-type]
    await publish("bounty.events", "k1", {"a": 1})
    assert sent == [("staging.bounty.events", {"a": 1}, "k1")]


# --- In-process dispatcher ----------------------------------------------------------------------------


async def _noop(session: Any, envelope: Any) -> None:
    return None


def consumers() -> list[Consumer]:
    analytics = Consumer("analytics-worker", [Topics.ANALYTICS, Topics.BOUNTY], {"*": _noop})
    email = Consumer("email-worker", [Topics.EMAIL], {EventType.EMAIL_VERIFICATION_REQUESTED: _noop})
    notif = Consumer("notification-worker", [Topics.BOUNTY], {EventType.BOUNTY_FUNDED: _noop})
    return [analytics, email, notif]


def test_dispatcher_selects_subscribers_by_topic_and_handler() -> None:
    d = InProcessDispatcher(consumers(), max_retries=0)
    assert [c.name for c in d.subscribers(Topics.ANALYTICS, EventType.USER_REGISTERED)] == [
        "analytics-worker"
    ]
    assert [c.name for c in d.subscribers(Topics.BOUNTY, EventType.BOUNTY_FUNDED)] == [
        "analytics-worker",
        "notification-worker",
    ]
    assert [c.name for c in d.subscribers(Topics.BOUNTY, EventType.BOUNTY_CREATED)] == ["analytics-worker"]


async def test_dispatcher_runs_each_subscriber(monkeypatch: pytest.MonkeyPatch) -> None:
    processed: list[str] = []

    async def fake_process(consumer: Consumer, envelope: EventEnvelope) -> bool:
        processed.append(consumer.name)
        return True

    monkeypatch.setattr(outbox_relay, "process_event", fake_process)
    row = outbox_row()
    await InProcessDispatcher(consumers(), max_retries=0)(row.topic, str(row.aggregate_id), row.payload)
    assert processed == ["analytics-worker"]


async def test_dispatcher_dead_letters_poison_event_without_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(consumer: Consumer, envelope: EventEnvelope) -> bool:
        raise ConnectionError("down")

    monkeypatch.setattr(outbox_relay, "process_event", failing)
    row = outbox_row()
    # max_retries=0: one attempt, then logged as dead-lettered; the relay is not blocked (no exception).
    await InProcessDispatcher(consumers(), max_retries=0)(row.topic, str(row.aggregate_id), row.payload)


async def test_dispatcher_aborts_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def failing(consumer: Consumer, envelope: EventEnvelope) -> bool:
        raise ConnectionError("down")

    monkeypatch.setattr(outbox_relay, "process_event", failing)
    stop = asyncio.Event()
    stop.set()
    row = outbox_row()
    with pytest.raises(RelayAborted):
        await InProcessDispatcher(consumers(), stop, max_retries=3)(
            row.topic, str(row.aggregate_id), row.payload
        )


async def test_dispatcher_drops_malformed_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake_process(consumer: Consumer, envelope: EventEnvelope) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(outbox_relay, "process_event", fake_process)
    await InProcessDispatcher(consumers(), max_retries=0)(Topics.ANALYTICS, "k", {"event_type": "nope"})
    assert not called
