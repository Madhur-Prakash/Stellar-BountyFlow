"""Compliance jobs: build data exports, expire old ones, run due account deletions, and sync the sanctions list.

| Job | Interval | What it does |
|---|---|---|
| ``data-exports`` | 10 s | Builds pending exports (a few per run), then clears archives past their expiry |
| ``account-deletion`` | 5 min | Anonymises accounts whose grace period is over, unless something blocks it |
| ``sanctions-list-refresh`` | ``SANCTIONS_LIST_REFRESH_SECONDS`` | Syncs LIST screening entries from the configured file or URL |
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

EXPORTS_JOB = "data-exports"
EXPORTS_INTERVAL = 10.0
EXPORTS_PER_RUN = 5

DELETION_JOB = "account-deletion"
DELETION_INTERVAL = 300.0
DELETIONS_PER_RUN = 20

SANCTIONS_JOB = "sanctions-list-refresh"


async def run_exports_once() -> dict[str, int]:
    from app.modules.compliance.exports import expire_ready, process_next

    built = 0
    for _ in range(EXPORTS_PER_RUN):
        async with session_scope() as session:
            if not await process_next(session):
                break
        built += 1
    async with session_scope() as session:
        expired = await expire_ready(session)
    if built or expired:
        logger.info("data_exports_job_completed", processed=built, expired=expired)
    return {"processed": built, "expired": expired}


async def run_deletions_once() -> int:
    from app.modules.compliance.deletion import execute_next

    handled = 0
    for _ in range(DELETIONS_PER_RUN):
        async with session_scope() as session:
            if not await execute_next(session):
                break
        handled += 1
    return handled


async def run_sanctions_once() -> dict[str, object]:
    from app.modules.compliance.screening import sync_configured_list

    async with session_scope() as session:
        return await sync_configured_list(session)


async def run_exports(stop: asyncio.Event) -> None:
    await run_periodic(EXPORTS_JOB, EXPORTS_INTERVAL, run_exports_once, stop, lock_ttl=300)


async def run_deletions(stop: asyncio.Event) -> None:
    await run_periodic(DELETION_JOB, DELETION_INTERVAL, run_deletions_once, stop, lock_ttl=600)


async def run_sanctions(stop: asyncio.Event) -> None:
    interval = float(get_settings().sanctions_list_refresh_seconds)
    await run_periodic(SANCTIONS_JOB, interval, run_sanctions_once, stop, lock_ttl=300)
