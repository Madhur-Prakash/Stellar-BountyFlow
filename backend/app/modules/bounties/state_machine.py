"""The single source of truth for bounty lifecycle transitions.

Clients never set a status directly; every change goes through `assert_transition`, which the domain services call
before mutating a bounty. On-chain escrow rules are enforced independently by the Soroban contract.
"""

from __future__ import annotations

from app.core.exceptions import InvalidStateTransition
from app.modules.bounties.models import BountyStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.DRAFT: frozenset({S.OPEN, S.CANCELLED}),
    # OPEN -> CANCEL_REQUESTED: a partially funded bounty is cancelled by refunding its deposit on-chain.
    S.OPEN: frozenset({S.FUNDING_PENDING, S.FUNDED, S.CANCELLED, S.CANCEL_REQUESTED, S.EXPIRED}),
    S.FUNDING_PENDING: frozenset({S.FUNDED, S.OPEN}),
    S.FUNDED: frozenset({S.IN_PROGRESS, S.CANCEL_REQUESTED, S.EXPIRED, S.FUNDING_PENDING}),
    S.IN_PROGRESS: frozenset({S.UNDER_REVIEW, S.FUNDED, S.COMPLETED, S.CANCEL_REQUESTED, S.DISPUTED}),
    S.UNDER_REVIEW: frozenset({S.IN_PROGRESS, S.FUNDED, S.COMPLETED, S.DISPUTED}),
    S.CANCEL_REQUESTED: frozenset({S.CANCELLED, S.DISPUTED, S.COMPLETED}),
    S.DISPUTED: frozenset(
        {S.FUNDED, S.IN_PROGRESS, S.UNDER_REVIEW, S.COMPLETED, S.CANCEL_REQUESTED, S.CANCELLED}
    ),
    S.EXPIRED: frozenset({S.CANCEL_REQUESTED, S.CANCELLED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
}

TERMINAL = frozenset({S.COMPLETED, S.CANCELLED})

# States in which the bounty is visible in the public marketplace by default.
MARKETPLACE_DEFAULT = (S.OPEN, S.FUNDING_PENDING, S.FUNDED, S.IN_PROGRESS, S.UNDER_REVIEW)

# States that accept new applications (subject to deadline and open positions).
ACCEPTING_APPLICATIONS = frozenset({S.OPEN, S.FUNDING_PENDING, S.FUNDED, S.IN_PROGRESS, S.UNDER_REVIEW})

# States in which a requester can accept an applicant (funds must be escrowed first).
CAN_ASSIGN = frozenset({S.FUNDED, S.IN_PROGRESS, S.UNDER_REVIEW})

# States in which assigned contributors can submit / be reviewed.
WORK_ACTIVE = frozenset({S.IN_PROGRESS, S.UNDER_REVIEW})

# Operational states whose aggregate status is derived from assignments and submissions.
DERIVED = frozenset({S.FUNDED, S.IN_PROGRESS, S.UNDER_REVIEW})

# States in which a dispute may be raised.
DISPUTABLE = frozenset({S.IN_PROGRESS, S.UNDER_REVIEW, S.CANCEL_REQUESTED})


def can_transition(current: S, target: S) -> bool:
    return current == target or target in TRANSITIONS.get(current, frozenset())


def assert_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        raise InvalidStateTransition(
            f"A bounty cannot move from {current.value} to {target.value}.",
            details={"from": current.value, "to": target.value},
        )


def derive_operational_status(active_assignments: int, pending_reviews: int) -> S:
    if pending_reviews > 0:
        return S.UNDER_REVIEW
    if active_assignments > 0:
        return S.IN_PROGRESS
    return S.FUNDED
