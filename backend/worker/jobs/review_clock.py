"""Review-clock job: marks submissions whose on-chain review window passed unanswered and notifies both parties
that the payment can be claimed (every 30 seconds)."""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

JOB_NAME = "review-clock"
INTERVAL_SECONDS = 30.0
LOCK_TTL_SECONDS = 120


async def run_review_clock_once() -> int:
    from app.modules.escrow.claims import mark_claimable

    async with session_scope() as session:
        return int(await mark_claimable(session) or 0)


async def run(stop: asyncio.Event) -> None:
    await run_periodic(JOB_NAME, INTERVAL_SECONDS, run_review_clock_once, stop, lock_ttl=LOCK_TTL_SECONDS)
