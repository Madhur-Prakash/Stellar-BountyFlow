"""Registry of event consumers. Domain modules register handlers here; the worker process wires each
consumer to a Kafka consumer group (or dispatches in-process when Kafka is disabled)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.events import EventEnvelope

Handler = Callable[[AsyncSession, EventEnvelope], Awaitable[None]]


@dataclass
class Consumer:
    name: str
    topics: list[str]
    handlers: dict[str, Handler] = field(default_factory=dict)  # event_type -> handler; "*" = all

    def handler_for(self, event_type: str) -> Handler | None:
        return self.handlers.get(event_type) or self.handlers.get("*")


_CONSUMERS: dict[str, Consumer] = {}


def consumer(name: str, topics: list[str]) -> Consumer:
    if name not in _CONSUMERS:
        _CONSUMERS[name] = Consumer(name=name, topics=topics)
    return _CONSUMERS[name]


def on(consumer_name: str, topics: list[str], *event_types: str) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        c = consumer(consumer_name, topics)
        for et in event_types:
            c.handlers[et] = fn
        return fn

    return decorator


def all_consumers() -> list[Consumer]:
    load_handlers()
    return list(_CONSUMERS.values())


def load_handlers() -> None:
    """Import modules that register handlers (idempotent)."""
    import app.blockchain.handlers
    import app.modules.analytics.handlers
    import app.modules.notifications.email_handlers
    import app.modules.notifications.handlers  # noqa: F401
