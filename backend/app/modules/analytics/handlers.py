"""Daily metric maintenance (consumer ``analytics-worker``).

Every domain event triggers a recomputation of the metrics for the UTC day the event occurred. Values are
recomputed from source tables and upserted, so redelivered or out-of-order events can never double-count.
"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.messaging.events import EventEnvelope, Topics
from app.messaging.registry import on
from app.modules.analytics.service import recompute_day

logger = get_logger(__name__)

CONSUMER = "analytics-worker"
TOPICS = [
    Topics.BOUNTY,
    Topics.APPLICATION,
    Topics.SUBMISSION,
    Topics.PAYMENT,
    Topics.ANALYTICS,
    Topics.BLOCKCHAIN,
]


@on(CONSUMER, TOPICS, "*")
async def handle_any_event(session: AsyncSession, envelope: EventEnvelope) -> None:
    occurred = envelope.occurred_at
    day = (occurred.astimezone(UTC) if occurred.tzinfo else occurred.replace(tzinfo=UTC)).date()
    await recompute_day(session, day)
    logger.debug("daily_metrics_recomputed", day=day.isoformat(), event_type=envelope.event_type)
