"""Platform gauges computed at scrape time for ``GET /metrics``.

Each collector is independent: one that fails (Redis down, RPC timeout) reports
``bountyflow_metrics_collector_up{collector="…"} 0`` and the rest of the scrape still succeeds.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.client import check_rpc
from app.cache.redis import check_redis
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.money import from_stroops
from app.core.security import utcnow
from app.db.health import check_database
from app.db.session import get_sessionmaker
from app.messaging.kafka import check_kafka
from app.messaging.models import OutboxEvent
from app.modules.admin.models import AuditLog
from app.modules.compliance import screening
from app.modules.compliance.models import (
    AccountDeletionRequest,
    DataExport,
    DeletionStatus,
    ExportStatus,
    ScreeningSource,
)
from app.modules.ops import health
from app.modules.ops.metrics import Counter, GaugeFamily, Histogram
from app.modules.payments.models import BlockchainTransaction, BountyEscrow, EscrowState, TxStatus

logger = get_logger(__name__)

Family = Counter | Histogram | GaugeFamily
Collector = Callable[[AsyncSession], Awaitable[list[Family]]]

# The relay marks an event dead-lettered (published_at set, error kept) after this many failed attempts.
OUTBOX_MAX_ATTEMPTS = 25
_HELD = (EscrowState.AWAITING_FUNDING, EscrowState.FUNDED, EscrowState.CANCEL_REQUESTED, EscrowState.DISPUTED)


def _age(then: float | None) -> float:
    return max(0.0, time.time() - then) if then else 0.0


async def outbox(session: AsyncSession) -> list[Family]:
    backlog, oldest = (
        await session.execute(
            select(func.count(OutboxEvent.id), func.min(OutboxEvent.created_at)).where(
                OutboxEvent.published_at.is_(None)
            )
        )
    ).one()
    dead = await session.scalar(
        select(func.count(OutboxEvent.id)).where(
            OutboxEvent.published_at.is_not(None), OutboxEvent.retry_count >= OUTBOX_MAX_ATTEMPTS
        )
    )
    return [
        GaugeFamily("bountyflow_outbox_backlog", "Outbox events not yet published to Kafka.").set(
            backlog or 0
        ),
        GaugeFamily(
            "bountyflow_outbox_oldest_unpublished_age_seconds", "Age of the oldest unpublished outbox event."
        ).set(_age(oldest.timestamp()) if oldest else 0),
        GaugeFamily(
            "bountyflow_outbox_dead_lettered_events",
            "Outbox events given up on after repeated publish failures (kept with their error).",
        ).set(dead or 0),
    ]


async def transactions(session: AsyncSession) -> list[Family]:
    rows = (
        await session.execute(
            select(
                BlockchainTransaction.transaction_type,
                func.count(BlockchainTransaction.id),
                func.min(BlockchainTransaction.submitted_at),
            )
            .where(BlockchainTransaction.status == TxStatus.SUBMITTED)
            .group_by(BlockchainTransaction.transaction_type)
        )
    ).all()
    pending = GaugeFamily(
        "bountyflow_chain_transactions_pending",
        "Submitted transactions not yet verified on-chain, by type.",
        ("type",),
    )
    oldest_age = 0.0
    for tx_type, count, oldest in rows:
        pending.set(count, tx_type.value)
        if oldest is not None:
            oldest_age = max(oldest_age, _age(oldest.timestamp()))
    failed_24h = await session.scalar(
        select(func.count(BlockchainTransaction.id)).where(
            BlockchainTransaction.status == TxStatus.FAILED,
            BlockchainTransaction.created_at >= utcnow() - timedelta(hours=24),
        )
    )
    held = (
        await session.execute(
            select(
                BountyEscrow.asset_identifier,
                func.sum(
                    BountyEscrow.funded_amount - BountyEscrow.paid_out_amount - BountyEscrow.refunded_amount
                ),
                func.count(BountyEscrow.id),
            )
            .where(BountyEscrow.state.in_(_HELD))
            .group_by(BountyEscrow.asset_identifier)
        )
    ).all()
    held_amount = GaugeFamily(
        "bountyflow_escrow_held_amount", "Amount held in live escrows (database view), by asset.", ("asset",)
    )
    held_count = GaugeFamily(
        "bountyflow_escrows_live", "Escrows holding or awaiting funds, by asset.", ("asset",)
    )
    for asset, amount, count in held:
        held_amount.set(float(amount or 0), asset)
        held_count.set(count, asset)
    return [
        pending,
        GaugeFamily(
            "bountyflow_chain_transaction_oldest_pending_age_seconds",
            "Age of the oldest submitted transaction still awaiting verification.",
        ).set(oldest_age),
        GaugeFamily(
            "bountyflow_chain_transactions_failed_24h", "Transactions that failed in the last 24 hours."
        ).set(failed_24h or 0),
        held_amount,
        held_count,
    ]


async def reconciliation(_: AsyncSession) -> list[Family]:
    result = await health.reconciliation()
    if result is None:
        return [GaugeFamily("bountyflow_reconciliation_audit_runs", "Whether an audit result exists.").set(0)]
    return [
        GaugeFamily(
            "bountyflow_reconciliation_mismatches",
            "Escrows whose database view differs from the contract in the last audit.",
        ).set(result.get("mismatches", 0)),
        GaugeFamily(
            "bountyflow_reconciliation_foreign_escrows",
            "Escrow ids occupied by an escrow BountyFlow did not create, in the last audit.",
        ).set(result.get("foreign", 0)),
        GaugeFamily("bountyflow_reconciliation_escrows_checked", "Escrows compared in the last audit.").set(
            result.get("checked", 0)
        ),
        GaugeFamily(
            "bountyflow_reconciliation_last_run_timestamp_seconds", "When the last reconciliation audit ran."
        ).set(result.get("at", 0)),
        GaugeFamily(
            "bountyflow_reconciliation_last_run_failed", "1 when the last audit could not reach the chain."
        ).set(1 if result.get("error") else 0),
    ]


async def kafka(_: AsyncSession) -> list[Family]:
    lag = GaugeFamily(
        "bountyflow_kafka_consumer_lag", "Messages behind the log end, per consumer group.", ("consumer",)
    )
    age = GaugeFamily(
        "bountyflow_kafka_consumer_lag_age_seconds",
        "How old the lag reading is, per consumer.",
        ("consumer",),
    )
    for consumer, value in sorted((await health.consumer_lag()).items()):
        lag.set(value.get("total", 0), consumer)
        age.set(_age(value.get("at")), consumer)
    return [lag, age]


async def worker(_: AsyncSession) -> list[Family]:
    success = GaugeFamily(
        "bountyflow_worker_job_last_success_timestamp_seconds",
        "Last successful run of a periodic job.",
        ("job",),
    )
    last_run = GaugeFamily(
        "bountyflow_worker_job_last_run_timestamp_seconds", "Last run of a periodic job.", ("job",)
    )
    duration = GaugeFamily(
        "bountyflow_worker_job_last_duration_seconds", "Duration of the last run.", ("job",)
    )
    consecutive = GaugeFamily(
        "bountyflow_worker_job_consecutive_failures", "Failed runs in a row (0 after a success).", ("job",)
    )
    runs = Counter("bountyflow_worker_job_runs_total", "Periodic job runs.", ("job",))
    failures = Counter("bountyflow_worker_job_failures_total", "Periodic job runs that raised.", ("job",))
    for job, state in sorted((await health.job_health()).items()):
        success.set(state.get("last_success", 0), job)
        last_run.set(state.get("last_run", 0), job)
        duration.set(state.get("last_duration", 0), job)
        consecutive.set(state.get("consecutive_failures", 0), job)
        runs.inc(job, amount=state.get("runs", 0))
        failures.inc(job, amount=state.get("failures", 0))
    heartbeat = GaugeFamily(
        "bountyflow_worker_heartbeat_age_seconds", "Seconds since each worker's last heartbeat.", ("worker",)
    )
    beats = await health.worker_heartbeats()
    for name, seconds in sorted(beats.items()):
        heartbeat.set(seconds, name)
    alive = GaugeFamily("bountyflow_workers_alive", "Workers with a heartbeat in the last 30 seconds.").set(
        len(beats)
    )
    return [success, last_run, duration, consecutive, runs, failures, heartbeat, alive]


async def sponsor(_: AsyncSession) -> list[Family]:
    from app.blockchain import sponsorship

    keypair = sponsorship.sponsor_keypair()
    configured = GaugeFamily("bountyflow_sponsor_configured", "1 when a fee sponsor key is configured.")
    if keypair is None:
        return [configured.set(0)]
    settings = get_settings()
    balance = await sponsorship.sponsor_balance()
    families: list[Family] = [
        configured.set(1),
        GaugeFamily(
            "bountyflow_sponsor_low_balance_threshold_xlm", "Balance below which sponsoring warns."
        ).set(settings.sponsor_low_balance_xlm),
        GaugeFamily("bountyflow_sponsor_min_balance_xlm", "Balance below which sponsoring stops.").set(
            settings.sponsor_min_balance_xlm
        ),
    ]
    if balance is not None:
        families.append(
            GaugeFamily(
                "bountyflow_sponsor_balance_xlm", "Native XLM balance of the fee sponsor account."
            ).set(float(from_stroops(balance)))
        )
    return families


async def compliance(session: AsyncSession) -> list[Family]:
    exports_pending = await session.scalar(
        select(func.count(DataExport.id)).where(
            DataExport.status.in_([ExportStatus.PENDING, ExportStatus.PROCESSING])
        )
    )
    exports_failed = await session.scalar(
        select(func.count(DataExport.id)).where(DataExport.status == ExportStatus.FAILED)
    )
    scheduled, overdue = (
        await session.execute(
            select(
                func.count(AccountDeletionRequest.id),
                func.count(AccountDeletionRequest.id).filter(
                    AccountDeletionRequest.scheduled_for < utcnow() - timedelta(days=1)
                ),
            ).where(AccountDeletionRequest.status == DeletionStatus.SCHEDULED)
        )
    ).one()
    blocks = await session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "screening.blocked", AuditLog.created_at >= utcnow() - timedelta(hours=24)
        )
    )
    counts = await screening.entry_counts(session)
    entries = GaugeFamily("bountyflow_screening_entries", "Active screening entries, by source.", ("source",))
    for source in ScreeningSource:
        entries.set(counts[source.value], source.value.lower())
    status = await screening.list_status() or {}
    loaded_at = status.get("loaded_at")
    list_age = GaugeFamily(
        "bountyflow_sanctions_list_age_seconds",
        "Seconds since the sanctions list was last loaded successfully.",
    )
    if loaded_at:
        from datetime import datetime

        list_age.set(_age(datetime.fromisoformat(loaded_at).timestamp()))
    return [
        GaugeFamily("bountyflow_data_exports_pending", "Data exports waiting to be built.").set(
            exports_pending or 0
        ),
        GaugeFamily("bountyflow_data_exports_failed", "Data exports that failed after all attempts.").set(
            exports_failed or 0
        ),
        GaugeFamily("bountyflow_account_deletions_scheduled", "Account deletions in their grace period.").set(
            scheduled or 0
        ),
        GaugeFamily(
            "bountyflow_account_deletions_overdue", "Scheduled deletions more than a day past their date."
        ).set(overdue or 0),
        GaugeFamily(
            "bountyflow_screening_blocks_24h", "Screening decisions that blocked, last 24 hours."
        ).set(blocks or 0),
        GaugeFamily(
            "bountyflow_sanctions_list_configured", "1 when a sanctions list source is configured."
        ).set(1 if status.get("configured") else 0),
        GaugeFamily("bountyflow_sanctions_list_error", "1 when the last sanctions list sync failed.").set(
            1 if status.get("error") else 0
        ),
        entries,
        list_age,
    ]


async def attestations(session: AsyncSession) -> list[Family]:
    """Attestation pipeline depth and the last chain-versus-database reconciliation.

    A stuck pipeline means contributors' completions never reach the registry, and a mismatch means the
    contract and the database disagree about what was attested. See docs/runbooks/reconciliation-mismatch.md.
    """
    from app.modules.reputation import service as reputation
    from app.modules.reputation.models import AttestationStatus, ChainCheck, CompletionAttestation

    by_status = GaugeFamily(
        "bountyflow_attestations", "Completion attestations, by pipeline status.", ("status",)
    )
    rows = (
        await session.execute(
            select(CompletionAttestation.status, func.count(CompletionAttestation.id)).group_by(
                CompletionAttestation.status
            )
        )
    ).all()
    counts = {status.value: 0 for status in AttestationStatus}
    for status, count in rows:
        counts[status.value] = int(count)
    for status_value, count in sorted(counts.items()):
        by_status.set(count, status_value)
    oldest = await session.scalar(
        select(func.min(CompletionAttestation.created_at)).where(
            CompletionAttestation.status == AttestationStatus.PENDING
        )
    )
    families: list[Family] = [
        by_status,
        GaugeFamily(
            "bountyflow_attestation_oldest_pending_age_seconds",
            "Age of the oldest attestation still waiting to reach the registry.",
        ).set(_age(oldest.timestamp()) if oldest else 0),
        GaugeFamily(
            "bountyflow_attestations_configured", "1 when an attester key and registry contract are set."
        ).set(1 if get_settings().stellar_attester_secret and get_settings().attestation_contract_id else 0),
    ]
    report = await reputation.last_reconciliation()
    if report is not None:
        families += [
            GaugeFamily(
                "bountyflow_attestation_reconciliation_checked", "Attestations compared in the last audit."
            ).set(report.checked),
            GaugeFamily(
                "bountyflow_attestation_reconciliation_mismatches",
                "Attestations whose database row disagrees with the registry.",
            ).set(report.mismatched),
            GaugeFamily(
                "bountyflow_attestation_reconciliation_missing",
                "Attestations the database has but the registry does not.",
            ).set(report.missing),
            GaugeFamily(
                "bountyflow_attestation_reconciliation_last_run_timestamp_seconds",
                "When the last attestation reconciliation finished.",
            ).set(report.finished_at.timestamp()),
        ]
    else:
        stale = await session.scalar(
            select(func.count(CompletionAttestation.id)).where(
                CompletionAttestation.chain_check == ChainCheck.MISMATCH
            )
        )
        families.append(
            GaugeFamily(
                "bountyflow_attestation_reconciliation_mismatches",
                "Attestations whose database row disagrees with the registry.",
            ).set(stale or 0)
        )
    return families


async def credentials(session: AsyncSession) -> list[Family]:
    """Issued verifiable credentials and how many are revoked (the public status list is built from these)."""
    from app.modules.credentials.models import IssuedCredential

    issued, revoked = (
        await session.execute(
            select(
                func.count(IssuedCredential.id),
                func.count(IssuedCredential.id).filter(IssuedCredential.revoked_at.is_not(None)),
            )
        )
    ).one()
    return [
        GaugeFamily("bountyflow_credentials_issued", "Verifiable credentials ever issued.").set(issued or 0),
        GaugeFamily(
            "bountyflow_credentials_revoked", "Credentials marked revoked in the public status list."
        ).set(revoked or 0),
        GaugeFamily("bountyflow_credentials_configured", "1 when a credential issuer key is configured.").set(
            1 if get_settings().credential_issuer_secret else 0
        ),
    ]


async def github(_: AsyncSession) -> list[Family]:
    """GitHub API backoff: while this is set, pull-request verification is paused."""
    from app.cache.redis import get_redis
    from app.modules.github.client import BACKOFF_KEY

    seconds = 0.0
    try:
        raw = await get_redis().get(BACKOFF_KEY)
        if raw:
            seconds = max(0.0, float(raw) - time.time())
    except (ValueError, TypeError):
        seconds = 0.0
    return [
        GaugeFamily(
            "bountyflow_github_backoff_seconds",
            "Seconds until GitHub API calls resume (0 when not rate-limited).",
        ).set(seconds),
        GaugeFamily("bountyflow_github_rate_limited", "1 while the GitHub API is rate-limiting us.").set(
            1 if seconds > 0 else 0
        ),
    ]


async def dependencies(_: AsyncSession) -> list[Family]:
    settings = get_settings()
    db, redis, rpc = await asyncio.gather(check_database(), check_redis(), check_rpc())
    kafka_ok = await check_kafka() if settings.kafka_enabled else None
    up = GaugeFamily(
        "bountyflow_dependency_up", "1 when a dependency answered its health check.", ("dependency",)
    )
    up.set(1 if db else 0, "database")
    up.set(1 if redis else 0, "redis")
    up.set(1 if rpc else 0, "soroban_rpc")
    if kafka_ok is not None:
        up.set(1 if kafka_ok else 0, "kafka")
    return [up]


COLLECTORS: dict[str, Collector] = {
    "outbox": outbox,
    "transactions": transactions,
    "reconciliation": reconciliation,
    "kafka": kafka,
    "worker": worker,
    "sponsor": sponsor,
    "attestations": attestations,
    "credentials": credentials,
    "github": github,
    "compliance": compliance,
    "dependencies": dependencies,
}

COLLECTOR_TIMEOUT_SECONDS = 8.0


async def collect() -> list[Family]:
    settings = get_settings()
    families: list[Family] = [
        GaugeFamily(
            "bountyflow_build_info", "Build and network of this API process.", ("version", "env", "network")
        ).set(1, settings.app_version, settings.app_env, settings.stellar_network)
    ]
    collector_up = GaugeFamily(
        "bountyflow_metrics_collector_up",
        "1 when a metrics collector succeeded on this scrape.",
        ("collector",),
    )
    async with get_sessionmaker()() as session:
        for name, collector in COLLECTORS.items():
            try:
                async with asyncio.timeout(COLLECTOR_TIMEOUT_SECONDS):
                    families.extend(await collector(session))
                collector_up.set(1, name)
            except Exception as exc:
                await session.rollback()
                logger.warning(
                    "metrics_collector_failed", collector=name, error=f"{type(exc).__name__}: {exc}"
                )
                collector_up.set(0, name)
    families.append(collector_up)
    return families
