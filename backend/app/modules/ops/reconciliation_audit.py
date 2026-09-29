"""Chain-versus-database reconciliation audit (read only).

Every escrow BountyFlow shows as live is read back from the contract and compared with ``bounty_escrows``. The
audit never writes to the escrow: a difference means a missed verification, a lost transaction or a bug, and an
operator decides what to do (usually ``POST /admin/bounties/{id}/reconcile``, which overwrites the database view
with verified chain state). See docs/runbooks/reconciliation-mismatch.md.

Escrows with a transaction still being confirmed are skipped: the difference there is expected and closes by
itself when verification runs.
"""

from __future__ import annotations

import time
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.reconciliation import ONCHAIN_TO_DB, matches_prepared_creation
from app.blockchain.soroban import EscrowSnapshot
from app.blockchain.transactions import ChainUnavailable, get_adapter
from app.core.logging import get_logger
from app.core.money import fmt, from_stroops
from app.core.security import utcnow
from app.modules.ops import health
from app.modules.payments.models import BlockchainTransaction, BountyEscrow, EscrowState, TxStatus, TxType

logger = get_logger(__name__)

BATCH_LIMIT = 200
MAX_DETAILS = 25
SETTLE_WINDOW = timedelta(minutes=3)
_TERMINAL = (EscrowState.NOT_CREATED, EscrowState.COMPLETED, EscrowState.CANCELLED)
RECENT_TERMINAL = timedelta(days=2)


def diff(escrow: BountyEscrow, snapshot: EscrowSnapshot | None) -> dict[str, list[str]]:
    """Fields where the database view differs from the contract, as ``{field: [database, chain]}``."""
    if snapshot is None:
        if escrow.state == EscrowState.NOT_CREATED:
            return {}
        return {"state": [escrow.state.value, "missing on chain"]}
    chain_state = ONCHAIN_TO_DB.get(snapshot.status)
    out: dict[str, list[str]] = {}
    if chain_state is not None and chain_state != escrow.state:
        out["state"] = [escrow.state.value, chain_state.value]
    amounts: tuple[tuple[str, Decimal, int], ...] = (
        ("funded_amount", escrow.funded_amount, snapshot.funded_amount),
        ("paid_out_amount", escrow.paid_out_amount, snapshot.paid_out_amount),
        ("refunded_amount", escrow.refunded_amount, snapshot.refunded_amount),
    )
    for name, recorded, stroops in amounts:
        onchain = from_stroops(stroops)
        if recorded != onchain:
            out[name] = [fmt(recorded), fmt(onchain)]
    return out


async def _authentic(session: AsyncSession, escrow: BountyEscrow, snapshot: EscrowSnapshot) -> bool:
    prepared: list[dict[str, Any] | None] = list(
        (
            await session.scalars(
                select(BlockchainTransaction.verification_metadata).where(
                    BlockchainTransaction.bounty_id == escrow.bounty_id,
                    BlockchainTransaction.transaction_type == TxType.ESCROW_CREATE,
                )
            )
        ).all()
    )
    return any(
        matches_prepared_creation(snapshot, escrow.onchain_bounty_id, (meta or {}).get("args") or {})
        for meta in prepared
    )


async def _settling(session: AsyncSession, escrow: BountyEscrow) -> bool:
    recent = utcnow() - SETTLE_WINDOW
    found = await session.scalar(
        select(BlockchainTransaction.id)
        .where(
            BlockchainTransaction.bounty_id == escrow.bounty_id,
            or_(
                BlockchainTransaction.status == TxStatus.SUBMITTED,
                (BlockchainTransaction.status == TxStatus.CONFIRMED)
                & (BlockchainTransaction.confirmed_at >= recent),
            ),
        )
        .limit(1)
    )
    return found is not None


async def run_audit(session: AsyncSession) -> dict[str, Any]:
    started = time.time()
    since = utcnow() - RECENT_TERMINAL
    escrows = (
        await session.scalars(
            select(BountyEscrow)
            .where(
                or_(
                    BountyEscrow.state.not_in(_TERMINAL),
                    (BountyEscrow.state != EscrowState.NOT_CREATED) & (BountyEscrow.updated_at >= since),
                )
            )
            .order_by(BountyEscrow.last_reconciled_at.asc().nulls_first())
            .limit(BATCH_LIMIT)
        )
    ).all()
    checked = skipped = foreign = 0
    mismatches: list[dict[str, Any]] = []
    error: str | None = None
    adapter = get_adapter()
    for escrow in escrows:
        if await _settling(session, escrow):
            skipped += 1
            continue
        try:
            snapshot = await adapter.read_escrow(bytes.fromhex(escrow.onchain_bounty_id), escrow.contract_id)
        except ChainUnavailable as exc:
            error = f"chain unavailable: {exc}"
            logger.warning("reconciliation_audit_chain_unavailable", error=str(exc))
            break
        checked += 1
        if snapshot is not None and not await _authentic(session, escrow, snapshot):
            foreign += 1
            logger.warning("reconciliation_audit_foreign_escrow", bounty_id=str(escrow.bounty_id))
            continue
        fields = diff(escrow, snapshot)
        if fields:
            logger.warning(
                "escrow_reconciliation_mismatch",
                bounty_id=str(escrow.bounty_id),
                onchain_bounty_id=escrow.onchain_bounty_id,
                fields=fields,
            )
            if len(mismatches) < MAX_DETAILS:
                mismatches.append(
                    {
                        "bounty_id": str(escrow.bounty_id),
                        "escrow_id": escrow.onchain_bounty_id,
                        "fields": fields,
                    }
                )
            else:
                mismatches.append({"bounty_id": str(escrow.bounty_id)})
    await session.rollback()  # read only
    result: dict[str, Any] = {
        "at": started,
        "duration_seconds": round(time.time() - started, 3),
        "checked": checked,
        "skipped_settling": skipped,
        "mismatches": len(mismatches),
        "foreign": foreign,
        "details": mismatches[:MAX_DETAILS],
        "error": error,
    }
    await health.save_reconciliation(result)
    if mismatches or foreign:
        logger.warning(
            "reconciliation_audit_completed", checked=checked, mismatches=len(mismatches), foreign=foreign
        )
    return result
