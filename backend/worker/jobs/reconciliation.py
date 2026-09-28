"""Transaction reconciliation job: re-verifies SUBMITTED transactions whose verification event was missed
or deferred (every 20 seconds)."""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

JOB_NAME = "tx-reconciliation"
INTERVAL_SECONDS = 20.0
LOCK_TTL_SECONDS = 120
BATCH_LIMIT = 50


async def run_reconciliation_once() -> int:
    from app.modules.payments.service import sweep_pending_transactions

    async with session_scope() as session:
        swept = int(await sweep_pending_transactions(session, limit=BATCH_LIMIT) or 0)
    if swept:
        logger.info("reconciliation_job_completed", transactions=swept)
    return swept


async def run(stop: asyncio.Event) -> None:
    await run_periodic(JOB_NAME, INTERVAL_SECONDS, run_reconciliation_once, stop, lock_ttl=LOCK_TTL_SECONDS)
