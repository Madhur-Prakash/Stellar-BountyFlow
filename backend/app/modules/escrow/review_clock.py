"""The review-window rules of the escrow contract (v2), mirrored for the backend state machine.

On-chain rules (contracts/bounty_escrow/src/lib.rs):

* ``submit_work`` records an assigned contributor's submission and starts the clock:
  ``claimable_at = submitted_at + review_window``. It needs a funded (or cancel-requested) escrow, a time before
  the escrow deadline, an unpaid milestone, and no pending or rejected review for that contributor.
* Before ``claimable_at`` the requester can stop the clock with ``request_changes`` (the next ``submit_work``
  starts a full new window) or ``reject_submission`` (final; only a dispute moves it on). From ``claimable_at``
  on, both are refused: paying is the only answer left, besides a dispute.
* ``claim`` pays the contributor from ``claimable_at`` on while the review is still pending.
* A dispute freezes claims and answers. When it is resolved, every pending review gets a full window again from
  the resolution (``clock_reset_at``): ``claimable_at = max(claimable_at, clock_reset_at + review_window)``.
* Paying the work (release, milestone release, batch leg, claim or a dispute resolution) removes the review.
* ``refund`` is refused while any review is pending, even after the deadline.

The backend never decides these outcomes; it refuses to prepare transactions the contract would reject, and it
mirrors the contract's verified state onto the submission (``onchain_state``, ``claimable_at``).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.exceptions import InvalidStateTransition
from app.modules.payments.models import EscrowState
from app.modules.submissions.models import OnchainReviewState

REVIEW_OPEN = frozenset({EscrowState.FUNDED, EscrowState.CANCEL_REQUESTED})

# Contract `ReviewState` -> the submission mirror.
FROM_CHAIN: dict[str, OnchainReviewState] = {
    "Pending": OnchainReviewState.PENDING,
    "ChangesRequested": OnchainReviewState.CHANGES_REQUESTED,
    "Rejected": OnchainReviewState.REJECTED,
}

# Allowed moves of the mirror (None = nothing recorded on-chain yet).
TRANSITIONS: dict[OnchainReviewState | None, frozenset[OnchainReviewState]] = {
    None: frozenset({OnchainReviewState.PENDING, OnchainReviewState.PAID}),
    OnchainReviewState.PENDING: frozenset(
        {OnchainReviewState.CHANGES_REQUESTED, OnchainReviewState.REJECTED, OnchainReviewState.PAID}
    ),
    OnchainReviewState.CHANGES_REQUESTED: frozenset({OnchainReviewState.PENDING, OnchainReviewState.PAID}),
    OnchainReviewState.REJECTED: frozenset({OnchainReviewState.PAID}),
    OnchainReviewState.PAID: frozenset(),
}


def can_move(current: OnchainReviewState | None, target: OnchainReviewState) -> bool:
    return current == target or target in TRANSITIONS.get(current, frozenset())


def effective_claimable_at(claimable_at: int, clock_reset_at: int | None, review_window: int) -> int:
    """Unix time the claim opens (see the module docstring for the dispute reset)."""
    if not clock_reset_at:
        return claimable_at
    return max(claimable_at, clock_reset_at + review_window)


def to_datetime(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)


def check_record(
    escrow_state: EscrowState,
    current: OnchainReviewState | None,
    *,
    now: int,
    deadline: int | None,
) -> None:
    """``submit_work`` preconditions (the contract checks them again)."""
    if escrow_state not in REVIEW_OPEN:
        raise InvalidStateTransition("Work can only be recorded on-chain while the escrow holds the reward.")
    if deadline is not None and now >= deadline:
        raise InvalidStateTransition(
            "The escrow deadline has passed, so work can no longer be recorded on-chain."
        )
    if current == OnchainReviewState.PENDING:
        raise InvalidStateTransition("This work is already recorded on-chain and waiting for review.")
    if current == OnchainReviewState.REJECTED:
        raise InvalidStateTransition(
            "The requester rejected this work on-chain. Raise a dispute to continue."
        )
    if current == OnchainReviewState.PAID:
        raise InvalidStateTransition("This work has already been paid.")


def check_answer(
    escrow_state: EscrowState, current: OnchainReviewState | None, *, now: int, opens_at: int
) -> None:
    """``request_changes`` / ``reject_submission`` preconditions."""
    if escrow_state not in REVIEW_OPEN:
        raise InvalidStateTransition("The escrow is not accepting review answers right now.")
    if current != OnchainReviewState.PENDING:
        raise InvalidStateTransition("There is no submission waiting for review on-chain.")
    if now >= opens_at:
        raise InvalidStateTransition(
            "The review window has passed, so the contributor can claim the payment. You can still pay it."
        )


def check_claim(
    escrow_state: EscrowState, current: OnchainReviewState | None, *, now: int, opens_at: int
) -> None:
    """``claim`` preconditions."""
    if escrow_state not in REVIEW_OPEN:
        raise InvalidStateTransition("Claims wait while the escrow is disputed or closed.")
    if current != OnchainReviewState.PENDING:
        raise InvalidStateTransition("There is no unanswered submission to claim.")
    if now < opens_at:
        raise InvalidStateTransition("The review window has not passed yet.")
