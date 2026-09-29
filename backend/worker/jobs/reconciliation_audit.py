"""Reconciliation audit job: compares live escrows with the contract every 10 minutes (read only) and publishes
the result for ``/metrics`` (``bountyflow_reconciliation_mismatches``). See docs/runbooks/reconciliation-mismatch.md.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

JOB_NAME = "reconciliation-audit"
INTERVAL_SECONDS = 600.0
LOCK_TTL_SECONDS = 540


async def run_audit_once() -> dict[str, Any]:
    from app.modules.ops.reconciliation_audit import run_audit

    async with session_scope() as session:
        return await run_audit(session)


async def run(stop: asyncio.Event) -> None:
    await run_periodic(JOB_NAME, INTERVAL_SECONDS, run_audit_once, stop, lock_ttl=LOCK_TTL_SECONDS)
