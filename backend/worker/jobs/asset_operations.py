"""Asset operation reconciliation job: settles submitted trustline and asset-contract transactions whose
verification a client never polled for, and expires stale unsigned ones (every 30 seconds)."""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

JOB_NAME = "asset-operations"
INTERVAL_SECONDS = 30.0
LOCK_TTL_SECONDS = 120
BATCH_LIMIT = 50


async def run_asset_operations_once() -> int:
    from app.modules.assets.operations import sweep

    async with session_scope() as session:
        swept = int(await sweep(session, limit=BATCH_LIMIT) or 0)
    if swept:
        logger.info("asset_operations_job_completed", operations=swept)
    return swept


async def run(stop: asyncio.Event) -> None:
    await run_periodic(JOB_NAME, INTERVAL_SECONDS, run_asset_operations_once, stop, lock_ttl=LOCK_TTL_SECONDS)
