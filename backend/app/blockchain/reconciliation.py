"""Reconciles the database escrow record with authoritative on-chain contract state."""

from __future__ import annotations

from typing import Any

from app.blockchain.soroban import EscrowSnapshot
from app.core.logging import get_logger
from app.core.money import from_stroops
from app.core.security import utcnow
from app.modules.payments.models import BountyEscrow, EscrowState

logger = get_logger(__name__)

ONCHAIN_TO_DB: dict[str, EscrowState] = {
    "AwaitingFunding": EscrowState.AWAITING_FUNDING,
    "Funded": EscrowState.FUNDED,
    "CancelRequested": EscrowState.CANCEL_REQUESTED,
    "Disputed": EscrowState.DISPUTED,
    "Completed": EscrowState.COMPLETED,
    "Cancelled": EscrowState.CANCELLED,
}


def apply_snapshot(escrow: BountyEscrow, snapshot: EscrowSnapshot | None) -> list[str]:
    """Overwrites DB escrow fields with chain truth. Returns the list of fields that changed (for auditing)."""
    changed: list[str] = []

    def _set(field: str, value: object) -> None:
        if getattr(escrow, field) != value:
            setattr(escrow, field, value)
            changed.append(field)

    if snapshot is None:
        if escrow.state != EscrowState.NOT_CREATED or escrow.funded_amount > 0:
            # An escrow we have already seen on-chain can't legitimately vanish: a missing read means an archived
            # entry (TTL lapse, restorable by anyone) or a misconfigured contract id. Keep the last verified state
            # rather than showing funded money as "not created".
            logger.warning(
                "escrow_missing_onchain",
                onchain_bounty_id=escrow.onchain_bounty_id,
                recorded_state=escrow.state.value,
            )
            return changed
        _set("state", EscrowState.NOT_CREATED)
    else:
        _set("state", ONCHAIN_TO_DB.get(snapshot.status, escrow.state))
        _set("funded_amount", from_stroops(snapshot.funded_amount))
        _set("paid_out_amount", from_stroops(snapshot.paid_out_amount))
        _set("refunded_amount", from_stroops(snapshot.refunded_amount))
        _set("required_amount", from_stroops(snapshot.required_amount))
        _set("requester_address", snapshot.requester)
        _set("arbiter_address", snapshot.arbiter)
        _set("onchain_deadline", snapshot.deadline)
        # v2 terms and clocks (a v1 escrow reads as one arbiter, threshold 1).
        _set("arbiter_addresses", list(snapshot.arbiter_set))
        _set("arbiter_threshold", snapshot.threshold)
        if snapshot.review_window:
            _set("review_window_seconds", snapshot.review_window)
        _set("dispute_round", snapshot.dispute_round)
        _set("clock_reset_at", snapshot.clock_reset_at or None)
    escrow.last_reconciled_at = utcnow()
    return changed


def matches_prepared_creation(
    snapshot: EscrowSnapshot, bounty_id_hex: str, create_args: dict[str, Any]
) -> bool:
    """True when an on-chain escrow is exactly the one a BountyFlow-prepared ``create_escrow`` would produce.

    Security: the escrow contract is permissionless — anyone can create an escrow at any bounty id with any token,
    arbiter and deadline. Chain state is only authoritative for an escrow whose immutable terms (requester, token,
    arbiter, reward, positions, deadline) equal the arguments the backend itself chose when preparing the creation
    (``blockchain_transactions.verification_metadata["args"]``). Anything else is a foreign escrow and must never
    be reconciled into the database (it could hold a worthless token or name an attacker-controlled arbiter).
    """
    try:
        v1_terms = (
            create_args.get("bounty_id") == bounty_id_hex
            and create_args.get("requester") == snapshot.requester
            and create_args.get("token") == snapshot.token
            and create_args.get("arbiter") == snapshot.arbiter
            and int(create_args["reward_per_position"]) == snapshot.reward_per_position
            and int(create_args["positions"]) == snapshot.positions
            and int(create_args["deadline"]) == snapshot.deadline
        )
        if not v1_terms:
            return False
        # v2 terms: the whole arbiter set, its threshold, the review window and the milestones. A v1-style
        # `create_escrow` prepared by BountyFlow always means one arbiter, threshold 1 and no milestones.
        arbiters = tuple(create_args.get("arbiters") or [create_args["arbiter"]])
        milestones = tuple(int(m) for m in create_args.get("milestones") or [])
        if (
            snapshot.arbiter_set != arbiters
            or snapshot.threshold != int(create_args.get("threshold", 1))
            or tuple(amount for amount, _ in snapshot.milestones) != milestones
        ):
            return False
        window = create_args.get("review_window")
        return window is None or snapshot.review_window == int(window)
    except (KeyError, TypeError, ValueError):
        return False
