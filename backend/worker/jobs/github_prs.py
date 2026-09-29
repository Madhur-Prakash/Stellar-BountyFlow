"""Pull request re-check job: refreshes the verification snapshot of open pull requests linked to active
submissions (every 30 seconds, picking only rows that are due). Rows become due on their schedule (5 minutes
with GITHUB_TOKEN, 20 without, backing off on failures) or immediately from a webhook delivery. A pull request
stops being re-checked once it is merged or closed, or its submission is approved or rejected."""

from __future__ import annotations

import asyncio
import time

from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

JOB_NAME = "github-pr-recheck"
INTERVAL_SECONDS = 30.0
LOCK_TTL_SECONDS = 240
BATCH_SIZE = 20


async def run_recheck_once() -> dict[str, int]:
    from app.modules.github.client import BACKOFF_KEY
    from app.modules.github.service import due_ids, stop_checking_closed_submissions, verify_pull_requests

    results = {"checked": 0, "stopped": 0}
    try:
        from app.cache.redis import get_redis

        until = await get_redis().get(BACKOFF_KEY)
        if until and float(until) > time.time():
            return results  # GitHub asked us to wait; the rows stay due
    except Exception as exc:
        logger.debug("github_backoff_read_failed", error=str(exc))
    try:
        async with session_scope() as session:
            results["stopped"] = await stop_checking_closed_submissions(session)
    except Exception:
        logger.exception("github_recheck_cleanup_failed")
    try:
        async with session_scope() as session:
            ids = await due_ids(session, BATCH_SIZE)
            results["checked"] = await verify_pull_requests(session, ids)
    except Exception:
        logger.exception("github_recheck_failed")
    if results["checked"]:
        logger.info("github_recheck_completed", **results)
    return results


async def run(stop: asyncio.Event) -> None:
    await run_periodic(JOB_NAME, INTERVAL_SECONDS, run_recheck_once, stop, lock_ttl=LOCK_TTL_SECONDS)
