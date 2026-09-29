"""On-chain attestation jobs (all no-ops while ATTESTATION_CONTRACT_ID / STELLAR_ATTESTER_SECRET are unset):

* ``attestation-pipeline`` (every 10 s): signs, submits and verifies queued attestations and revocations.
* ``attestation-backfill`` (every 10 min, first run at start-up): queues attestations for verified payouts that
  have none, e.g. payouts settled before the feature was switched on.
* ``attestation-reconciliation`` (every 30 min): re-reads attested rows from the contract and flags drift.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

PIPELINE_JOB = "attestation-pipeline"
PIPELINE_INTERVAL_SECONDS = 10.0
PIPELINE_LOCK_TTL_SECONDS = 600
PIPELINE_BATCH = 10

BACKFILL_JOB = "attestation-backfill"
BACKFILL_INTERVAL_SECONDS = 600.0
BACKFILL_LOCK_TTL_SECONDS = 300
BACKFILL_BATCH = 200

RECONCILIATION_JOB = "attestation-reconciliation"
RECONCILIATION_INTERVAL_SECONDS = 1800.0
RECONCILIATION_LOCK_TTL_SECONDS = 600
RECONCILIATION_BATCH = 200


async def run_pipeline_once() -> int:
    from app.modules.reputation.service import run_pipeline

    async with session_scope() as session:
        processed = await run_pipeline(session, limit=PIPELINE_BATCH)
    if processed:
        logger.info("attestation_pipeline_completed", attestations=processed)
    return processed


async def run_backfill_once() -> int:
    from app.modules.reputation.service import backfill

    async with session_scope() as session:
        return await backfill(session, limit=BACKFILL_BATCH)


async def run_reconciliation_once() -> int:
    from app.modules.reputation.chain import get_config
    from app.modules.reputation.service import reconcile

    if not get_config().reads_enabled:
        return 0
    async with session_scope() as session:
        report = await reconcile(session, limit=RECONCILIATION_BATCH)
    if report.mismatched or report.missing:
        logger.error("attestation_reconciliation_drift", mismatched=report.mismatched, missing=report.missing)
    elif report.checked:
        logger.info("attestation_reconciliation_completed", checked=report.checked)
    return report.checked


async def run_pipeline(stop: asyncio.Event) -> None:
    await run_periodic(
        PIPELINE_JOB, PIPELINE_INTERVAL_SECONDS, run_pipeline_once, stop, lock_ttl=PIPELINE_LOCK_TTL_SECONDS
    )


async def run_backfill(stop: asyncio.Event) -> None:
    await run_periodic(
        BACKFILL_JOB, BACKFILL_INTERVAL_SECONDS, run_backfill_once, stop, lock_ttl=BACKFILL_LOCK_TTL_SECONDS
    )


async def run_reconciliation(stop: asyncio.Event) -> None:
    await run_periodic(
        RECONCILIATION_JOB,
        RECONCILIATION_INTERVAL_SECONDS,
        run_reconciliation_once,
        stop,
        lock_ttl=RECONCILIATION_LOCK_TTL_SECONDS,
    )
