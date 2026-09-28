"""Bounty lifecycle job: expires overdue bounties and emits deadline reminders (every 60 seconds)."""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

JOB_NAME = "bounty-lifecycle"
INTERVAL_SECONDS = 60.0
LOCK_TTL_SECONDS = 300


async def run_lifecycle_once() -> dict[str, int]:
    from app.modules.bounties.service import expire_overdue, notify_deadlines

    results = {"expired": 0, "deadline_notices": 0}
    # Separate transactions: a failure in one step must not roll back the other.
    try:
        async with session_scope() as session:
            results["expired"] = int(await expire_overdue(session) or 0)
    except Exception:
        logger.exception("lifecycle_expire_failed")
    try:
        async with session_scope() as session:
            results["deadline_notices"] = int(await notify_deadlines(session) or 0)
    except Exception:
        logger.exception("lifecycle_deadline_notices_failed")
    if any(results.values()):
        logger.info("lifecycle_job_completed", **results)
    return results


async def run(stop: asyncio.Event) -> None:
    await run_periodic(JOB_NAME, INTERVAL_SECONDS, run_lifecycle_once, stop, lock_ttl=LOCK_TTL_SECONDS)
