"""On-chain completion attestations: queueing, the submission pipeline, backfill, reconciliation and revocation.

**What an attestation states.** One attestation per (bounty, contributor): that contributor completed that bounty
and was paid in full. Escrow v2 pays in several ways — a single release, milestone payouts, one leg of a batch
payout, a claim after the review window, or a paying dispute resolution — so the attested amount is the *sum* of
that contributor's confirmed payments on the bounty, in the bounty's reward asset, and the individual payments are
the evidence behind it. A completion is queued only once the contract reports the contributor as ``Paid`` (their
assignment is COMPLETED), which is also what makes a batch payout produce several attestations from one hash.

**Pipeline** (``advance``), per row, one business operation per database transaction and never a row lock held
across network I/O:

1. PENDING: *claim* the row (lock, count the attempt, push the next attempt out, commit). Then, with no
   transaction open, ask the registry whether this completion is already attested (``find``) — if so the record is
   adopted, which makes a retry after a lost response idempotent — otherwise the attester signs and sends
   ``attest``. The hash is written in its own transaction, and the row becomes SUBMITTED.
2. SUBMITTED: once the network reports SUCCESS, the record is read back from the contract and compared with the
   completion. Only a matching record makes the row CONFIRMED, the only state shown as "completed on-chain". A
   failed or never-included transaction goes back to PENDING; the contract itself refuses a second attestation of
   the same completion (``AlreadyAttested``), so nothing is ever recorded twice.
3. REVOKING: the attester sends ``revoke`` with the reason; the row becomes REVOKED once the contract reports it.

Rows are queued from the verified payment events (emitted only after the escrow reports the contributor ``Paid``)
and by the backfill job. The reconciliation job re-reads attested rows from the contract and flags any drift.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, Select, Uuid, and_, exists, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.transactions import ChainRejected, ChainUnavailable, TxOutcome
from app.cache import keys
from app.cache.invalidation import invalidate_profile
from app.cache.redis import cache_delete, cache_get_json, cache_set_json, cached_json
from app.core.exceptions import Conflict, InvalidStateTransition, NotFound, ServiceUnavailable
from app.core.logging import get_logger
from app.core.money import fmt, to_stroops
from app.core.schemas import Page, PageParams, asset_amounts
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.bounties.models import Bounty
from app.modules.payments.models import (
    BlockchainTransaction,
    BountyEscrow,
    PaymentRecord,
    PaymentStatus,
    TxStatus,
    TxType,
)
from app.modules.reputation.chain import (
    AttestationChain,
    AttestationError,
    Completion,
    OnchainAttestation,
    attester_lock,
    get_chain,
    get_config,
)
from app.modules.reputation.models import AttestationStatus, ChainCheck, CompletionAttestation
from app.modules.reputation.schemas import (
    AdminAttestationOut,
    AttestationDetail,
    AttestationOut,
    ChainRead,
    MyAttestationCounts,
    ReconciliationReport,
    ReputationSummary,
    serialize_attestation,
)
from app.modules.users import repository as users_repo
from app.modules.users import service as users_service
from app.modules.users.models import User

logger = get_logger(__name__)

MAX_ATTEMPTS = 12
BASE_BACKOFF = timedelta(seconds=15)
MAX_BACKOFF = timedelta(hours=1)
# A sent transaction the network still does not know after its time bounds plus this grace is resubmitted.
INCLUSION_GRACE = timedelta(seconds=90)
SETTLE_RECHECK = timedelta(seconds=20)
CHAIN_READ_TTL = 30  # seconds a public page's live contract read is cached

# Shown publicly as "completed on-chain" (or revoked): verified rows that reconciliation has not flagged.
VISIBLE = (AttestationStatus.CONFIRMED, AttestationStatus.REVOKING, AttestationStatus.REVOKED)
IN_FLIGHT = (AttestationStatus.PENDING, AttestationStatus.SUBMITTED, AttestationStatus.REVOKING)
_FLAGGED = (ChainCheck.MISMATCH, ChainCheck.MISSING)


def _summary_key(username: str) -> str:
    return f"{keys.PREFIX}:reputation:summary:{username.lower()}"


def _chain_read_key(onchain_id: int) -> str:
    return f"{keys.PREFIX}:reputation:chain:{onchain_id}"


RECONCILIATION_REPORT_KEY = f"{keys.PREFIX}:reputation:reconciliation"


def _backoff(attempts: int) -> timedelta:
    return min(BASE_BACKOFF * (2 ** max(attempts - 1, 0)), MAX_BACKOFF)


def _require_writes() -> None:
    if not get_config().writes_enabled:
        raise ServiceUnavailable(
            "On-chain attestations are not configured on this server (ATTESTATION_CONTRACT_ID / "
            "STELLAR_ATTESTER_SECRET).",
            code="attestations_disabled",
        )


# --- Queueing -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Totals:
    """A contributor's confirmed payments on one bounty, aggregated in SQL."""

    payments: int
    amount: Decimal
    first_paid_at: datetime | None
    last_paid_at: datetime | None


async def _totals(session: AsyncSession, bounty_id: uuid.UUID, contributor_id: uuid.UUID) -> _Totals:
    row = (
        await session.execute(
            select(
                func.count(PaymentRecord.id),
                func.coalesce(func.sum(PaymentRecord.amount), 0),
                func.min(PaymentRecord.settled_at),
                func.max(PaymentRecord.settled_at),
            ).where(
                PaymentRecord.bounty_id == bounty_id,
                PaymentRecord.contributor_id == contributor_id,
                PaymentRecord.payment_status == PaymentStatus.CONFIRMED,
            )
        )
    ).one()
    return _Totals(int(row[0] or 0), Decimal(row[1] or 0), row[2], row[3])


async def _paid_address(
    session: AsyncSession, tx: BlockchainTransaction, contributor_id: uuid.UUID
) -> str | None:
    """The address this contributor was paid at: their leg of a batch payout, the transaction's destination, the
    address locked on-chain by ASSIGN, or their current verified wallet."""
    legs = (tx.verification_metadata or {}).get("legs") or []
    if legs:
        from app.modules.submissions.models import BountySubmission

        ids = [uuid.UUID(str(leg["submission_id"])) for leg in legs if leg.get("submission_id")]
        mine = set(
            (
                await session.scalars(
                    select(BountySubmission.id).where(
                        BountySubmission.id.in_(ids), BountySubmission.contributor_id == contributor_id
                    )
                )
            ).all()
        )
        for leg in legs:
            if uuid.UUID(str(leg.get("submission_id"))) in mine and leg.get("contributor"):
                return str(leg["contributor"])
    if tx.destination_address:
        return tx.destination_address
    locked = await session.scalar(
        select(BlockchainTransaction.destination_address)
        .join(BountyAssignment, BountyAssignment.id == BlockchainTransaction.assignment_id)
        .where(
            BountyAssignment.bounty_id == tx.bounty_id,
            BountyAssignment.contributor_id == contributor_id,
            BlockchainTransaction.transaction_type == TxType.ASSIGN,
            BlockchainTransaction.status == TxStatus.CONFIRMED,
        )
        .order_by(BlockchainTransaction.confirmed_at.desc())
        .limit(1)
    )
    if locked:
        return locked
    wallet = await users_repo.primary_wallet(session, contributor_id, tx.network)
    return wallet.public_address if wallet is not None else None


async def enqueue(
    session: AsyncSession, *, transaction_id: uuid.UUID, contributor_id: uuid.UUID
) -> CompletionAttestation | None:
    """Queue (or refresh) the attestation of one completed contribution, in the caller's transaction.

    Returns None, queueing nothing, while attestations are off, or when the contributor's position is not fully
    paid yet: their assignment must be COMPLETED, which the escrow settlement sets only after the contract
    reported them ``Paid``. Idempotent: one row per (bounty, contributor)."""
    config = get_config()
    if not config.writes_enabled or not config.contract_id:
        return None
    tx = await session.get(BlockchainTransaction, transaction_id)
    if tx is None or tx.status != TxStatus.CONFIRMED or not tx.transaction_hash or tx.bounty_id is None:
        return None
    row = (
        await session.execute(
            select(Bounty, BountyEscrow, BountyAssignment)
            .join(BountyEscrow, BountyEscrow.bounty_id == Bounty.id)
            .join(
                BountyAssignment,
                and_(
                    BountyAssignment.bounty_id == Bounty.id,
                    BountyAssignment.contributor_id == contributor_id,
                ),
            )
            .where(Bounty.id == tx.bounty_id)
        )
    ).first()
    if row is None:
        return None
    bounty, escrow, assignment = row
    if assignment.status != AssignmentStatus.COMPLETED:
        return None  # a partial payment: the position is not complete yet
    totals = await _totals(session, bounty.id, contributor_id)
    if totals.payments == 0 or totals.amount <= 0:
        return None
    address = await _paid_address(session, tx, contributor_id)
    escrow_contract = tx.contract_id or escrow.contract_id
    if not address or not escrow_contract or len(tx.transaction_hash) != 64:
        logger.warning("attestation_completion_incomplete", transaction_id=str(tx.id))
        return None
    identifier = escrow.asset_identifier or bounty.reward_asset_identifier or "native"
    token = escrow.asset_contract_id or config.network.sac_contract_id(identifier)
    completed_at = tx.confirmed_at or totals.last_paid_at or utcnow()
    values = {
        "bounty_id": bounty.id,
        "contributor_id": contributor_id,
        "assignment_id": assignment.id,
        "payout_transaction_id": tx.id,
        "network": config.network.network,
        "contract_id": config.contract_id,
        "contributor_address": address,
        "onchain_bounty_id": escrow.onchain_bounty_id,
        "escrow_contract_id": escrow_contract,
        "payout_tx_hash": tx.transaction_hash,
        "asset_identifier": identifier,
        "token_contract_id": token,
        "amount": totals.amount,
        "payments_count": totals.payments,
        "first_paid_at": totals.first_paid_at,
        "completed_at": completed_at,
    }
    insert = pg_insert(CompletionAttestation).values(
        id=uuid.uuid4(), status=AttestationStatus.PENDING, attempts=0, next_attempt_at=utcnow(), **values
    )
    # A late payment (a last milestone) may land before the attestation is recorded: refresh the totals while the
    # row is still queued, and never touch a row that is already on-chain.
    await session.execute(
        insert.on_conflict_do_update(
            constraint="uq_completion_attestations_bounty_contributor",
            set_={
                "amount": insert.excluded.amount,
                "payments_count": insert.excluded.payments_count,
                "first_paid_at": insert.excluded.first_paid_at,
                "completed_at": insert.excluded.completed_at,
                "payout_transaction_id": insert.excluded.payout_transaction_id,
                "payout_tx_hash": insert.excluded.payout_tx_hash,
                "contributor_address": insert.excluded.contributor_address,
                "next_attempt_at": utcnow(),
            },
            where=CompletionAttestation.status == AttestationStatus.PENDING,
        )
    )
    return await session.scalar(
        select(CompletionAttestation).where(
            CompletionAttestation.bounty_id == bounty.id,
            CompletionAttestation.contributor_id == contributor_id,
        )
    )


async def backfill(session: AsyncSession, limit: int = 100) -> int:
    """Queue attestations for completions that have none yet (payouts settled before the feature was on).

    One query finds the completed assignments whose contributor has confirmed payments but no attestation row;
    each is then queued in its own transaction."""
    config = get_config()
    if not config.writes_enabled:
        return 0
    settling = (
        select(
            PaymentRecord.bounty_id,
            PaymentRecord.contributor_id,
            # The transaction of the most recent confirmed payment. Postgres has no max() for uuid, and the
            # largest uuid would be arbitrary anyway, so order the ids by settlement and take the first.
            func.array_agg(
                aggregate_order_by(
                    PaymentRecord.blockchain_transaction_id,
                    PaymentRecord.settled_at.desc().nullslast(),
                ),
                type_=ARRAY(Uuid),
            )[1].label("transaction_id"),
        )
        .join(BlockchainTransaction, BlockchainTransaction.id == PaymentRecord.blockchain_transaction_id)
        .join(
            BountyAssignment,
            and_(
                BountyAssignment.bounty_id == PaymentRecord.bounty_id,
                BountyAssignment.contributor_id == PaymentRecord.contributor_id,
            ),
        )
        .where(
            PaymentRecord.payment_status == PaymentStatus.CONFIRMED,
            BlockchainTransaction.status == TxStatus.CONFIRMED,
            BlockchainTransaction.network == config.network.network,
            BountyAssignment.status == AssignmentStatus.COMPLETED,
            ~exists().where(
                and_(
                    CompletionAttestation.bounty_id == PaymentRecord.bounty_id,
                    CompletionAttestation.contributor_id == PaymentRecord.contributor_id,
                )
            ),
        )
        .group_by(PaymentRecord.bounty_id, PaymentRecord.contributor_id)
        .order_by(func.max(PaymentRecord.settled_at).asc().nulls_last())
        .limit(limit)
    )
    missing = (await session.execute(settling)).all()
    await session.rollback()
    queued = 0
    for _bounty_id, contributor_id, transaction_id in missing:
        if transaction_id is None:
            continue
        try:
            if (
                await enqueue(session, transaction_id=transaction_id, contributor_id=contributor_id)
                is not None
            ):
                await session.commit()
                queued += 1
            else:
                await session.rollback()
        except Exception:
            logger.exception("attestation_backfill_failed", transaction_id=str(transaction_id))
            await session.rollback()
    if queued:
        logger.info("attestation_backfill_queued", count=queued)
    return queued


# --- Pipeline -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Claim:
    """Everything a chain call needs, read while the row was locked. Nothing here is a live ORM object, so the
    lock is released (the transaction committed) before any network call."""

    id: uuid.UUID
    status: AttestationStatus
    completion: Completion
    onchain_id: int | None
    attestation_tx_hash: str | None
    revocation_tx_hash: str | None
    revocation_reason: str
    submitted_at: datetime | None


def _completion(row: CompletionAttestation) -> Completion:
    return Completion(
        contributor=row.contributor_address,
        bounty_id=bytes.fromhex(row.onchain_bounty_id),
        escrow_contract=row.escrow_contract_id,
        payout_tx=bytes.fromhex(row.payout_tx_hash),
        token=row.token_contract_id,
        amount=to_stroops(row.amount),
        completed_at=int(row.completed_at.timestamp()),
    )


async def _lock(
    session: AsyncSession, attestation_id: uuid.UUID, *, skip_locked: bool = False
) -> CompletionAttestation | None:
    return await session.scalar(
        select(CompletionAttestation)
        .where(CompletionAttestation.id == attestation_id)
        .with_for_update(of=CompletionAttestation, skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )


async def _claim(session: AsyncSession, attestation_id: uuid.UUID) -> _Claim | None:
    """Transaction 1: take the row, count the attempt and schedule the next one, then commit so the lock is gone
    before any network call. A crash between here and the result simply retries (and adopts what is on-chain)."""
    row = await _lock(session, attestation_id, skip_locked=True)
    if row is None or row.status not in IN_FLIGHT:
        await session.rollback()
        return None
    if row.next_attempt_at is not None and row.next_attempt_at > utcnow():
        await session.rollback()
        return None
    row.attempts += 1
    if row.attempts > MAX_ATTEMPTS and row.status == AttestationStatus.PENDING:
        row.status = AttestationStatus.FAILED
        row.next_attempt_at = None
        row.last_error = "The attestation could not be recorded after repeated attempts."
        await session.commit()
        logger.error("attestation_failed", attestation_id=str(attestation_id), attempts=row.attempts)
        return None
    row.next_attempt_at = utcnow() + _backoff(row.attempts)
    claim = _Claim(
        id=row.id,
        status=row.status,
        completion=_completion(row),
        onchain_id=row.onchain_id,
        attestation_tx_hash=row.attestation_tx_hash,
        revocation_tx_hash=row.revocation_tx_hash,
        revocation_reason=row.revocation_reason or "Attestation revoked",
        submitted_at=row.submitted_at,
    )
    await session.commit()
    return claim


def _event_payload(row: CompletionAttestation) -> dict[str, Any]:
    return {
        "attestation_id": row.id,
        "bounty_id": row.bounty_id,
        "contributor_id": row.contributor_id,
        "title": row.bounty.title,
        "amount": fmt(row.amount),
        "asset_code": row.bounty.reward_asset or "XLM",
        "onchain_id": row.onchain_id or 0,
        "status": row.status.value,
    }


async def _after_change(row: CompletionAttestation) -> None:
    await invalidate_profile(row.contributor.username)
    await cache_delete(_summary_key(row.contributor.username))
    if row.onchain_id:
        await cache_delete(_chain_read_key(row.onchain_id))


async def _record_failure(
    session: AsyncSession, claim: _Claim, error: str, *, permanent: bool = False
) -> None:
    """Transaction: keep the reason, and stop retrying when the contract refused it for good."""
    row = await _lock(session, claim.id)
    if row is None:
        await session.rollback()
        return
    row.last_error = error[:500]
    if permanent and row.status in (AttestationStatus.PENDING, AttestationStatus.SUBMITTED):
        row.status = AttestationStatus.FAILED
        row.next_attempt_at = None
        logger.error("attestation_refused", attestation_id=str(row.id), error=error[:300])
    await session.commit()


async def _adopt(session: AsyncSession, claim: _Claim, record: OnchainAttestation) -> AttestationStatus:
    """Transaction: record ``record`` (read from the contract) as this row's attestation, if it is exactly this
    completion. Every write — the row, the audit entry and the outbox event — commits together."""
    row = await _lock(session, claim.id)
    if row is None:
        await session.rollback()
        return AttestationStatus.FAILED
    if row.status in (AttestationStatus.CONFIRMED, AttestationStatus.REVOKED):
        await session.rollback()
        return row.status
    if not record.matches(claim.completion):
        row.status = AttestationStatus.FAILED
        row.chain_check = ChainCheck.MISMATCH
        row.chain_checked_at = utcnow()
        row.next_attempt_at = None
        row.last_error = f"The on-chain record #{record.id} does not match this completion."
        await session.commit()
        logger.error("attestation_mismatch", attestation_id=str(row.id), onchain_id=record.id)
        return row.status
    row.onchain_id = record.id
    row.attested_at = record.attested_datetime
    row.chain_check = ChainCheck.MATCH
    row.chain_checked_at = utcnow()
    row.confirmed_at = utcnow()
    row.last_error = None
    row.next_attempt_at = None
    if record.revoked:
        row.status = AttestationStatus.REVOKED
        row.revoked_at = record.revoked_datetime
        row.revocation_reason = record.revocation_reason or row.revocation_reason
    else:
        row.status = AttestationStatus.CONFIRMED
        add_event(
            session,
            event_type=EventType.ATTESTATION_CONFIRMED,
            aggregate_type="attestation",
            aggregate_id=row.id,
            payload=_event_payload(row),
        )
    audit.record(
        session,
        actor_id=None,
        action="attestation.confirmed",
        entity_type="attestation",
        entity_id=row.id,
        bounty_id=row.bounty_id,
        metadata={"onchain_id": record.id, "hash": row.attestation_tx_hash, "payout": row.payout_tx_hash},
    )
    await session.commit()
    logger.info("attestation_confirmed", attestation_id=str(row.id), onchain_id=record.id)
    await _after_change(row)
    return row.status


async def _mark_submitted(session: AsyncSession, claim: _Claim, tx_hash: str) -> None:
    """Transaction: make the sent transaction's hash durable before waiting for the network."""
    row = await _lock(session, claim.id)
    if row is None:
        await session.rollback()
        return
    if row.status == AttestationStatus.PENDING:
        row.status = AttestationStatus.SUBMITTED
        row.attestation_tx_hash = tx_hash
        row.submitted_at = utcnow()
        row.last_error = None
        row.next_attempt_at = utcnow() + SETTLE_RECHECK
    await session.commit()


async def _submit(session: AsyncSession, chain: AttestationChain, claim: _Claim) -> AttestationStatus:
    completion = claim.completion
    try:
        existing = await chain.find(completion.bounty_id, completion.contributor, completion.payout_tx)
    except (ChainUnavailable, AttestationError) as exc:
        await _record_failure(session, claim, str(exc))
        return AttestationStatus.PENDING
    if existing is not None:
        return await _adopt(session, claim, existing)
    try:
        async with attester_lock():
            tx_hash = await chain.attest(completion)
    except AttestationError as exc:
        if exc.code == 2:  # AlreadyAttested: a concurrent attempt landed first
            existing = await chain.find(completion.bounty_id, completion.contributor, completion.payout_tx)
            if existing is not None:
                return await _adopt(session, claim, existing)
        await _record_failure(session, claim, f"{exc.name}: {exc.message}", permanent=exc.permanent)
        return AttestationStatus.PENDING
    except (ChainUnavailable, ChainRejected) as exc:
        await _record_failure(session, claim, str(exc))
        return AttestationStatus.PENDING
    await _mark_submitted(session, claim, tx_hash)
    outcome = await chain.wait_for_outcome(tx_hash)
    return await _settle(session, chain, _replace_hash(claim, tx_hash), outcome)


def _replace_hash(claim: _Claim, tx_hash: str) -> _Claim:
    return _Claim(
        id=claim.id,
        status=AttestationStatus.SUBMITTED,
        completion=claim.completion,
        onchain_id=claim.onchain_id,
        attestation_tx_hash=tx_hash,
        revocation_tx_hash=claim.revocation_tx_hash,
        revocation_reason=claim.revocation_reason,
        submitted_at=utcnow(),
    )


async def _requeue(session: AsyncSession, claim: _Claim, reason: str) -> AttestationStatus:
    """Transaction: the attest transaction failed or was never included; queue a fresh attempt."""
    row = await _lock(session, claim.id)
    if row is None:
        await session.rollback()
        return AttestationStatus.FAILED
    if row.status == AttestationStatus.SUBMITTED:
        row.status = AttestationStatus.PENDING
        row.attestation_tx_hash = None
        row.submitted_at = None
        row.last_error = reason[:500]
        row.next_attempt_at = utcnow() + _backoff(row.attempts)
    status = row.status
    await session.commit()
    return status


async def _wait_again(session: AsyncSession, claim: _Claim) -> AttestationStatus:
    row = await _lock(session, claim.id)
    if row is None:
        await session.rollback()
        return AttestationStatus.FAILED
    row.next_attempt_at = utcnow() + SETTLE_RECHECK
    status = row.status
    await session.commit()
    return status


async def _settle(
    session: AsyncSession, chain: AttestationChain, claim: _Claim, outcome: TxOutcome | None = None
) -> AttestationStatus:
    """The network's answer for a sent attestation. All chain reads happen here, before any row is locked."""
    if not claim.attestation_tx_hash:
        return await _requeue(session, claim, "No attestation transaction was recorded.")
    try:
        outcome = outcome or await chain.get_outcome(claim.attestation_tx_hash)
        record = None
        if outcome.status in ("SUCCESS", "FAILED"):
            c = claim.completion
            record = await chain.find(c.bounty_id, c.contributor, c.payout_tx)
    except (ChainUnavailable, AttestationError) as exc:
        await _record_failure(session, claim, str(exc))
        return await _wait_again(session, claim)
    if record is not None:
        return await _adopt(session, claim, record)
    if outcome.status == "SUCCESS":
        return await _wait_again(session, claim)  # the RPC may lag the ledger for a moment
    if outcome.status == "FAILED":
        return await _requeue(session, claim, outcome.failure_reason or "The attestation transaction failed.")
    timeout = timedelta(seconds=get_config().network.tx_timeout_seconds) + INCLUSION_GRACE
    if outcome.status == "NOT_FOUND" and claim.submitted_at and utcnow() > claim.submitted_at + timeout:
        return await _requeue(session, claim, "The attestation transaction was never included.")
    return await _wait_again(session, claim)


async def _finalize_revocation(
    session: AsyncSession, claim: _Claim, record: OnchainAttestation
) -> AttestationStatus:
    """Transaction: the contract reports the attestation revoked. The row, the credentials it backs, the audit
    entry and the outbox event all commit together."""
    from app.modules.credentials.service import revoke_for_attestation

    row = await _lock(session, claim.id)
    if row is None:
        await session.rollback()
        return AttestationStatus.FAILED
    if row.status == AttestationStatus.REVOKED:
        await session.rollback()
        return row.status
    row.status = AttestationStatus.REVOKED
    row.revoked_at = record.revoked_datetime or utcnow()
    row.revocation_reason = record.revocation_reason or row.revocation_reason
    row.chain_check = ChainCheck.MATCH
    row.chain_checked_at = utcnow()
    row.next_attempt_at = None
    row.last_error = None
    await revoke_for_attestation(session, row.id, row.revocation_reason or "Attestation revoked")
    add_event(
        session,
        event_type=EventType.ATTESTATION_REVOKED,
        aggregate_type="attestation",
        aggregate_id=row.id,
        payload=_event_payload(row),
    )
    audit.record(
        session,
        actor_id=row.revoked_by_id,
        action="attestation.revoked",
        entity_type="attestation",
        entity_id=row.id,
        bounty_id=row.bounty_id,
        metadata={
            "onchain_id": row.onchain_id,
            "reason": row.revocation_reason,
            "hash": row.revocation_tx_hash,
        },
    )
    await session.commit()
    logger.info("attestation_revoked", attestation_id=str(row.id), onchain_id=row.onchain_id)
    await _after_change(row)
    return row.status


async def _mark_revocation_sent(session: AsyncSession, claim: _Claim, tx_hash: str) -> None:
    row = await _lock(session, claim.id)
    if row is None:
        await session.rollback()
        return
    if row.status == AttestationStatus.REVOKING:
        row.revocation_tx_hash = tx_hash
        row.submitted_at = utcnow()
        row.last_error = None
        row.next_attempt_at = utcnow() + SETTLE_RECHECK
    await session.commit()


async def _revoke(session: AsyncSession, chain: AttestationChain, claim: _Claim) -> AttestationStatus:
    if claim.onchain_id is None:
        await _record_failure(session, claim, "The attestation has no on-chain id.", permanent=True)
        return AttestationStatus.FAILED
    try:
        record = await chain.get(claim.onchain_id)
        if record is not None and record.revoked:
            return await _finalize_revocation(session, claim, record)
        if claim.revocation_tx_hash:
            outcome = await chain.get_outcome(claim.revocation_tx_hash)
            timeout = timedelta(seconds=get_config().network.tx_timeout_seconds) + INCLUSION_GRACE
            waiting = outcome.status in ("PENDING", "SUCCESS") or (
                outcome.status == "NOT_FOUND"
                and claim.submitted_at is not None
                and utcnow() <= claim.submitted_at + timeout
            )
            if waiting:
                return await _wait_again(session, claim)
        async with attester_lock():
            tx_hash = await chain.revoke(claim.onchain_id, claim.revocation_reason)
    except AttestationError as exc:
        if exc.code == 6:  # AlreadyRevoked
            record = await chain.get(claim.onchain_id)
            if record is not None:
                return await _finalize_revocation(session, claim, record)
        await _record_failure(session, claim, f"{exc.name}: {exc.message}")
        return AttestationStatus.REVOKING
    except (ChainUnavailable, ChainRejected) as exc:
        await _record_failure(session, claim, str(exc))
        return AttestationStatus.REVOKING
    await _mark_revocation_sent(session, claim, tx_hash)
    outcome = await chain.wait_for_outcome(tx_hash)
    if outcome.status == "SUCCESS":
        record = await chain.get(claim.onchain_id)
        if record is not None and record.revoked:
            return await _finalize_revocation(session, claim, record)
    return await _wait_again(session, claim)


async def advance(session: AsyncSession, attestation_id: uuid.UUID) -> AttestationStatus | None:
    """Move one row forward (idempotent). Returns None when another worker holds it or it is not due."""
    claim = await _claim(session, attestation_id)
    if claim is None:
        return None
    chain = get_chain()
    if claim.status == AttestationStatus.PENDING:
        return await _submit(session, chain, claim)
    if claim.status == AttestationStatus.SUBMITTED:
        return await _settle(session, chain, claim)
    return await _revoke(session, chain, claim)


async def run_pipeline(session: AsyncSession, limit: int = 10) -> int:
    """Worker job: advance every due row (queued, awaiting an outcome, or being revoked)."""
    if not get_config().writes_enabled:
        return 0
    due = (
        await session.scalars(
            select(CompletionAttestation.id)
            .where(
                CompletionAttestation.status.in_(IN_FLIGHT),
                (CompletionAttestation.next_attempt_at.is_(None))
                | (CompletionAttestation.next_attempt_at <= utcnow()),
            )
            .order_by(CompletionAttestation.next_attempt_at.asc().nulls_first())
            .limit(limit)
        )
    ).all()
    await session.rollback()
    processed = 0
    for attestation_id in due:
        try:
            if await advance(session, attestation_id) is not None:
                processed += 1
        except Exception:
            logger.exception("attestation_advance_failed", attestation_id=str(attestation_id))
            await session.rollback()
    return processed


# --- Reconciliation -----------------------------------------------------------------------


async def reconcile(session: AsyncSession, limit: int = 100) -> ReconciliationReport:
    """Re-read attested rows from the contract (least recently checked first) and flag any drift.

    A record that no longer matches, or cannot be found, is flagged and stops being shown as completed on-chain.
    A revocation made on-chain outside this database (for example by another deployment sharing the attester) is
    applied here. Each row is read from the chain with nothing locked, then written in its own transaction."""
    chain = get_chain()
    rows = (
        (
            await session.scalars(
                select(CompletionAttestation)
                .where(
                    CompletionAttestation.status.in_(VISIBLE),
                    CompletionAttestation.onchain_id.is_not(None),
                )
                .order_by(CompletionAttestation.chain_checked_at.asc().nulls_first())
                .limit(limit)
            )
        )
        .unique()
        .all()
    )
    queue = [(r.id, r.onchain_id or 0, _completion(r), r.contributor.username) for r in rows]
    await session.rollback()
    counts = {"checked": 0, "matching": 0, "mismatched": 0, "missing": 0, "revoked_on_chain": 0}
    touched: set[str] = set()
    for attestation_id, onchain_id, completion, username in queue:
        try:
            record = await chain.get(onchain_id)
        except (ChainUnavailable, AttestationError) as exc:
            logger.warning("attestation_reconcile_deferred", error=str(exc))
            break
        counts["checked"] += 1
        touched.add(username)
        if record is not None and record.matches(completion) and record.revoked:
            counts["matching"] += 1
            counts["revoked_on_chain"] += 1
            claim = _Claim(
                id=attestation_id,
                status=AttestationStatus.REVOKING,
                completion=completion,
                onchain_id=onchain_id,
                attestation_tx_hash=None,
                revocation_tx_hash=None,
                revocation_reason=record.revocation_reason or "Attestation revoked",
                submitted_at=None,
            )
            await _finalize_revocation(session, claim, record)
            continue
        row = await _lock(session, attestation_id)
        if row is None:
            await session.rollback()
            continue
        row.chain_checked_at = utcnow()
        if record is None:
            row.chain_check = ChainCheck.MISSING
            counts["missing"] += 1
            logger.error("attestation_missing_onchain", attestation_id=str(row.id), onchain_id=onchain_id)
        elif not record.matches(completion):
            row.chain_check = ChainCheck.MISMATCH
            counts["mismatched"] += 1
            logger.error("attestation_mismatch", attestation_id=str(row.id), onchain_id=onchain_id)
        else:
            row.chain_check = ChainCheck.MATCH
            counts["matching"] += 1
        await session.commit()
    by_status = (
        await session.execute(
            select(CompletionAttestation.status, func.count(CompletionAttestation.id)).group_by(
                CompletionAttestation.status
            )
        )
    ).all()
    await session.rollback()
    report = ReconciliationReport(
        **counts,
        by_status={str(getattr(k, "value", k)): int(v) for k, v in by_status},
        finished_at=utcnow(),
    )
    await cache_set_json(RECONCILIATION_REPORT_KEY, report.model_dump(mode="json"), 7 * 24 * 3600)
    await cache_delete(*[_summary_key(u) for u in touched])
    return report


async def last_reconciliation() -> ReconciliationReport | None:
    raw = await cache_get_json(RECONCILIATION_REPORT_KEY)
    return ReconciliationReport.model_validate(raw) if raw else None


# --- Revocation and retries (staff) ---------------------------------------------------------


async def request_revocation(
    session: AsyncSession, staff: User, attestation_id: uuid.UUID, reason: str
) -> AttestationOut:
    _require_writes()
    row = await _lock(session, attestation_id)
    if row is None:
        await session.rollback()
        raise NotFound("Attestation not found.")
    if row.status == AttestationStatus.REVOKED:
        await session.rollback()
        raise Conflict("This attestation is already revoked.")
    if row.status != AttestationStatus.CONFIRMED or row.onchain_id is None:
        await session.rollback()
        raise InvalidStateTransition("Only an attestation confirmed on-chain can be revoked.")
    row.status = AttestationStatus.REVOKING
    row.revocation_reason = reason
    row.revoked_by_id = staff.id
    row.revocation_tx_hash = None
    row.attempts = 0
    row.next_attempt_at = utcnow()
    audit.record(
        session,
        actor_id=staff.id,
        action="attestation.revocation_requested",
        entity_type="attestation",
        entity_id=row.id,
        bounty_id=row.bounty_id,
        metadata={"onchain_id": row.onchain_id, "reason": reason},
    )
    await session.commit()  # intent first; the chain call runs with nothing locked
    try:
        await advance(session, attestation_id)
    except Exception:  # the pipeline job finishes it
        logger.exception("attestation_revoke_deferred", attestation_id=str(attestation_id))
        await session.rollback()
    return serialize_attestation(await _load(session, attestation_id))


async def retry(session: AsyncSession, attestation_id: uuid.UUID) -> AttestationOut:
    _require_writes()
    row = await _lock(session, attestation_id)
    if row is None:
        await session.rollback()
        raise NotFound("Attestation not found.")
    if row.status != AttestationStatus.FAILED or row.chain_check == ChainCheck.MISMATCH:
        await session.rollback()
        raise InvalidStateTransition("Only a failed attestation can be retried.")
    row.status = AttestationStatus.PENDING
    row.attempts = 0
    row.next_attempt_at = utcnow()
    row.last_error = None
    await session.commit()
    return serialize_attestation(await _load(session, attestation_id))


# --- Queries --------------------------------------------------------------------------------


async def _load(session: AsyncSession, attestation_id: uuid.UUID) -> CompletionAttestation:
    row = await session.scalar(
        select(CompletionAttestation)
        .where(CompletionAttestation.id == attestation_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFound("Attestation not found.")
    return row


def _public[T](stmt: Select[T]) -> Select[T]:
    """Only completions verified on-chain, on bounties that are still visible."""
    return stmt.join(Bounty, Bounty.id == CompletionAttestation.bounty_id).where(
        CompletionAttestation.status.in_(VISIBLE),
        (CompletionAttestation.chain_check.is_(None)) | (CompletionAttestation.chain_check.not_in(_FLAGGED)),
        Bounty.is_hidden.is_(False),
    )


async def _page(
    session: AsyncSession, base: Select[CompletionAttestation], params: PageParams
) -> Page[AttestationOut]:
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(CompletionAttestation.completed_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    config = get_config()
    return Page[AttestationOut].build([serialize_attestation(r, config) for r in rows], total, params)


async def public_attestations(
    session: AsyncSession, username: str, params: PageParams
) -> Page[AttestationOut]:
    user = await users_service.get_public_user(session, username)
    base = _public(select(CompletionAttestation)).where(CompletionAttestation.contributor_id == user.id)
    return await _page(session, base, params)


async def my_attestations(session: AsyncSession, user: User, params: PageParams) -> Page[AttestationOut]:
    base = select(CompletionAttestation).where(CompletionAttestation.contributor_id == user.id)
    return await _page(session, base, params)


async def my_counts(session: AsyncSession, user: User) -> MyAttestationCounts:
    rows = dict(
        (
            await session.execute(
                select(CompletionAttestation.status, func.count(CompletionAttestation.id))
                .where(CompletionAttestation.contributor_id == user.id)
                .group_by(CompletionAttestation.status)
            )
        ).all()
    )

    def count(*statuses: AttestationStatus) -> int:
        return sum(int(rows.get(s, 0)) for s in statuses)

    return MyAttestationCounts(
        confirmed=count(AttestationStatus.CONFIRMED, AttestationStatus.REVOKING),
        in_progress=count(AttestationStatus.PENDING, AttestationStatus.SUBMITTED),
        revoked=count(AttestationStatus.REVOKED),
        failed=count(AttestationStatus.FAILED),
    )


async def summary(session: AsyncSession, username: str) -> ReputationSummary:
    """A contributor's reputation from attested completions only. Totals are grouped per asset in SQL: amounts of
    different assets are never added together."""
    user = await users_service.get_public_user(session, username)
    config = get_config()

    async def load() -> dict[str, Any]:
        standing = _public(select(CompletionAttestation.id)).where(
            CompletionAttestation.contributor_id == user.id,
            CompletionAttestation.status != AttestationStatus.REVOKED,
        )
        totals = (
            await session.execute(
                select(
                    CompletionAttestation.asset_identifier,
                    func.sum(CompletionAttestation.amount),
                    func.count(CompletionAttestation.id),
                    func.min(CompletionAttestation.completed_at),
                    func.max(CompletionAttestation.completed_at),
                )
                .where(CompletionAttestation.id.in_(standing))
                .group_by(CompletionAttestation.asset_identifier)
            )
        ).all()
        revoked = await session.scalar(
            select(func.count()).select_from(
                _public(select(CompletionAttestation.id))
                .where(
                    CompletionAttestation.contributor_id == user.id,
                    CompletionAttestation.status == AttestationStatus.REVOKED,
                )
                .subquery()
            )
        )
        completions = sum(int(row[2]) for row in totals)
        firsts = [row[3] for row in totals if row[3] is not None]
        lasts = [row[4] for row in totals if row[4] is not None]
        result = ReputationSummary(
            enabled=config.reads_enabled,
            attested_completions=completions,
            revoked=int(revoked or 0),
            earned=asset_amounts({str(row[0]): Decimal(row[1] or 0) for row in totals}),
            first_completed_at=min(firsts) if firsts else None,
            last_completed_at=max(lasts) if lasts else None,
            network=config.network.network,
            contract_id=config.contract_id,
            contract_explorer_url=config.contract_url(),
            attester_address=config.attester_address,
        )
        return result.model_dump(mode="json")

    return ReputationSummary.model_validate(await cached_json(_summary_key(username), 60, load))


async def public_attestation(session: AsyncSession, ref: str) -> AttestationDetail:
    """One attestation by its on-chain id (digits) or row id, with a live read of the contract."""
    stmt = select(CompletionAttestation)
    if ref.isdigit():
        config = get_config()
        stmt = stmt.where(
            CompletionAttestation.onchain_id == int(ref),
            CompletionAttestation.network == config.network.network,
            CompletionAttestation.contract_id == (config.contract_id or ""),
        )
    else:
        try:
            stmt = stmt.where(CompletionAttestation.id == uuid.UUID(ref))
        except ValueError as exc:
            raise NotFound("Attestation not found.") from exc
    row = await session.scalar(_public(stmt))
    if row is None:
        raise NotFound("Attestation not found.")
    out = serialize_attestation(row)
    chain = await live_read(row)
    return AttestationDetail(**out.model_dump(), chain=chain)


async def live_read(row: CompletionAttestation) -> ChainRead | None:
    """Reads the record from the contract now (cached briefly) and compares it with the completion."""
    config = get_config()
    if row.onchain_id is None or not config.reads_enabled or row.contract_id != config.contract_id:
        return None
    key = _chain_read_key(row.onchain_id)
    cached = await cache_get_json(key)
    if cached is not None:
        return ChainRead.model_validate(cached)
    completion = _completion(row)
    try:
        record = await get_chain().get(row.onchain_id)
    except (ChainUnavailable, AttestationError) as exc:
        return ChainRead(
            checked_at=datetime.now(UTC),
            found=False,
            matches=False,
            revoked=False,
            record=None,
            error=str(exc),
        )
    read = ChainRead(
        checked_at=datetime.now(UTC),
        found=record is not None,
        matches=record is not None and record.matches(completion),
        revoked=bool(record and record.revoked),
        record=record.to_dict() if record else None,
    )
    await cache_set_json(key, read.model_dump(mode="json"), CHAIN_READ_TTL)
    return read


async def admin_list(
    session: AsyncSession, status: AttestationStatus | None, params: PageParams
) -> Page[AdminAttestationOut]:
    base = select(CompletionAttestation)
    if status is not None:
        base = base.where(CompletionAttestation.status == status)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(CompletionAttestation.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    config = get_config()
    items = [
        AdminAttestationOut(
            **serialize_attestation(r, config).model_dump(),
            attempts=r.attempts,
            last_error=r.last_error,
            chain_check=r.chain_check.value if r.chain_check else None,
            chain_checked_at=r.chain_checked_at,
        )
        for r in rows
    ]
    return Page[AdminAttestationOut].build(items, total, params)
