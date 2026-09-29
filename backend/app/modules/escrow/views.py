"""Escrow v2 additions to the submission, bounty and dispute views, and the rules those services share.

Kept here so the owning services only call one helper per touch point.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, InvalidStateTransition, ValidationFailed
from app.core.security import utcnow
from app.modules.applications.models import BountyAssignment
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties.models import Bounty
from app.modules.escrow import chain as escrow_chain
from app.modules.escrow import milestones as milestone_service
from app.modules.escrow import review_clock
from app.modules.escrow.models import BountyMilestone, MilestoneStatus
from app.modules.escrow.schemas import MilestoneOut, OnchainReviewOut, SubmissionMilestone
from app.modules.submissions.models import BountySubmission, OnchainReviewState, SubmissionStatus

# Submissions that still hold a milestone (a new one for the same milestone must wait).
_LIVE = (
    SubmissionStatus.SUBMITTED,
    SubmissionStatus.RESUBMITTED,
    SubmissionStatus.REVISION_REQUESTED,
    SubmissionStatus.APPROVED,
)


async def check_new_submission(
    session: AsyncSession, bounty: Bounty, assignment: BountyAssignment, milestone_id: uuid.UUID | None
) -> uuid.UUID | None:
    """One submission per assignment, or one per milestone on a milestone bounty. Returns the milestone id."""
    milestones = await milestone_service.for_bounty(session, bounty.id)
    if not milestones:
        if milestone_id is not None:
            raise ValidationFailed("This bounty has no milestones.")
        existing = await session.scalar(
            select(BountySubmission.id).where(BountySubmission.assignment_id == assignment.id)
        )
        if existing:
            raise Conflict("You have already submitted work. Update it when a revision is requested.")
        return None
    milestone = next((m for m in milestones if m.id == milestone_id), None)
    if milestone is None:
        raise ValidationFailed(
            "Choose the milestone this work is for.",
            details=[{"field": "milestone_id", "message": "Required"}],
        )
    if milestone.status != MilestoneStatus.OPEN:
        raise Conflict("This milestone has already been paid.")
    live = await session.scalar(
        select(BountySubmission.id).where(
            BountySubmission.assignment_id == assignment.id,
            BountySubmission.milestone_id == milestone.id,
            BountySubmission.status.in_(_LIVE),
        )
    )
    if live:
        raise Conflict(
            "You have already submitted work for this milestone. Update it when a revision is requested."
        )
    return milestone.id


async def milestone_submit_open(
    session: AsyncSession, bounty: Bounty, assignment: BountyAssignment
) -> bool | None:
    """For a milestone bounty: whether an open milestone still waits for this contributor's work. None otherwise."""
    milestones = await milestone_service.for_bounty(session, bounty.id)
    if not milestones:
        return None
    open_ids = {m.id for m in milestones if m.status == MilestoneStatus.OPEN}
    if not open_ids:
        return False
    taken = (
        await session.scalars(
            select(BountySubmission.milestone_id).where(
                BountySubmission.assignment_id == assignment.id,
                BountySubmission.milestone_id.in_(open_ids),
                BountySubmission.status.in_(_LIVE),
            )
        )
    ).all()
    return bool(open_ids - set(taken))


async def payment_amount(session: AsyncSession, bounty: Bounty, submission: BountySubmission) -> Decimal:
    """What approving ``submission`` owes: the milestone amount, or one reward."""
    if submission.milestone_id is None:
        return bounty.reward_amount
    milestone = await session.get(BountyMilestone, submission.milestone_id)
    if milestone is None:
        return bounty.reward_amount
    if milestone.status != MilestoneStatus.OPEN:
        raise InvalidStateTransition("This milestone has already been paid.")
    return milestone.amount


def guard_offchain_review(submission: BountySubmission) -> None:
    """While the contract's review clock runs, a revision request or a rejection must be signed on-chain, or the
    contributor could still claim the payment when the window passes."""
    if submission.onchain_state == OnchainReviewState.PENDING:
        raise Conflict(
            "This work is recorded on-chain and its review clock is running. Answer it with your wallet so the "
            "clock stops.",
            code="onchain_review_pending",
        )


def _milestone_brief(m: BountyMilestone) -> SubmissionMilestone:
    return SubmissionMilestone(id=m.id, position=m.position, title=m.title, amount=m.amount, status=m.status)


async def decorate_submissions(session: AsyncSession, pairs: Sequence[tuple[BountySubmission, Any]]) -> None:
    """Adds ``milestone`` and ``onchain_review`` to serialized submissions (``SubmissionOut``)."""
    if not pairs:
        return
    milestone_ids = {s.milestone_id for s, _ in pairs if s.milestone_id}
    milestones: dict[uuid.UUID, BountyMilestone] = {}
    if milestone_ids:
        rows = await session.scalars(select(BountyMilestone).where(BountyMilestone.id.in_(milestone_ids)))
        milestones = {m.id: m for m in rows.all()}
    escrows = await bounty_repo.escrows(session, list({s.bounty_id for s, _ in pairs}))
    assignment_ids = {s.assignment_id for s, _ in pairs}
    onchain = set(
        (
            await session.scalars(
                select(BountyAssignment.id).where(
                    BountyAssignment.id.in_(assignment_ids), BountyAssignment.onchain_assigned.is_(True)
                )
            )
        ).all()
    )
    now = int(utcnow().timestamp())
    for submission, out in pairs:
        milestone = milestones.get(submission.milestone_id) if submission.milestone_id else None
        out.milestone = _milestone_brief(milestone) if milestone else None
        escrow = escrows.get(submission.bounty_id)
        view = escrow_chain.onchain_review_view(submission, escrow)
        out.onchain_review = OnchainReviewOut(**view) if view else None
        # Whether the contributor can record this work on-chain now (v2 escrow, assigned on-chain, open review).
        out.can_record_onchain = bool(
            escrow is not None
            and escrow.contract_version >= 2
            and escrow.state in review_clock.REVIEW_OPEN
            and (escrow.onchain_deadline is None or now < escrow.onchain_deadline)
            and submission.assignment_id in onchain
            and submission.status in (SubmissionStatus.SUBMITTED, SubmissionStatus.RESUBMITTED)
            and submission.onchain_state in (None, OnchainReviewState.CHANGES_REQUESTED)
            and (milestone is None or milestone.status == MilestoneStatus.OPEN)
        )


async def bounty_extras(session: AsyncSession, bounty: Bounty) -> dict[str, Any]:
    """Fields the bounty detail adds for escrow v2."""
    milestones: list[MilestoneOut] = await milestone_service.serialized(session, bounty.id)
    return {
        "milestones": milestones,
        "review_window_seconds": bounty.review_window_seconds
        or escrow_chain.escrow_settings().default_review_window,
    }


async def milestone_counts(session: AsyncSession, bounty_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not bounty_ids:
        return {}
    rows = await session.execute(
        select(BountyMilestone.bounty_id, func.count(BountyMilestone.id))
        .where(BountyMilestone.bounty_id.in_(bounty_ids))
        .group_by(BountyMilestone.bounty_id)
    )
    return {bounty_id: int(count) for bounty_id, count in rows.all()}


def check_review_window(seconds: int | None) -> int | None:
    """A requested review window within this server's bounds (None keeps the default)."""
    if seconds is None:
        return None
    config = escrow_chain.escrow_settings()
    if not config.min_review_window <= seconds <= config.max_review_window:
        raise ValidationFailed(
            "The review window is outside what this server allows.",
            details=[
                {
                    "field": "review_window_seconds",
                    "message": f"Between {config.min_review_window} and {config.max_review_window} seconds",
                }
            ],
        )
    return seconds


async def apply_create(session: AsyncSession, bounty: Bounty, data: Any) -> None:
    """``BountyCreate`` escrow v2 fields: the review window and the milestones."""
    bounty.review_window_seconds = check_review_window(data.review_window_seconds)
    if data.milestones:
        await milestone_service.replace(session, bounty, data.milestones)


async def apply_update(session: AsyncSession, bounty: Bounty, data: Any, changed: set[str]) -> None:
    """``BountyUpdate`` escrow v2 fields. Milestones are money terms, so they follow the reward (draft only)."""
    if "review_window_seconds" in changed:
        bounty.review_window_seconds = check_review_window(data.review_window_seconds)
    if "milestones" in changed and data.milestones is not None:
        if bounty.status.value != "DRAFT":
            raise InvalidStateTransition("Milestones can only be changed while the bounty is a draft.")
        await milestone_service.replace(session, bounty, data.milestones)
    elif {"reward_amount", "positions_available"} & changed:
        current = await milestone_service.for_bounty(session, bounty.id)
        if current:
            milestone_service.validate(
                [_as_input(m) for m in current],
                bounty.reward_amount,
                bounty.positions_available,
                bounty.reward_asset or "XLM",
            )


def _as_input(m: BountyMilestone) -> Any:
    from app.modules.escrow.schemas import MilestoneInput

    return MilestoneInput(title=m.title, description=m.description, amount=m.amount)


async def check_split(session: AsyncSession, bounty: Bounty, escrow: Any, amount: Decimal | None) -> Decimal:
    """A SPLIT decision pays the contributor part of their open position; the arbiters execute it on-chain."""
    if escrow is None or escrow.state.value != "DISPUTED" or escrow.contract_version < 2:
        raise ValidationFailed(
            "A split is executed by the arbiters on a frozen v2 escrow. Choose release or refund instead."
        )
    if amount is None:
        raise ValidationFailed(
            "Enter what the contributor receives.",
            details=[{"field": "contributor_amount", "message": "Required for a split"}],
        )
    milestones = await milestone_service.for_bounty(session, bounty.id)
    open_value = (
        sum((m.amount for m in milestones if m.status == MilestoneStatus.OPEN), Decimal(0))
        if milestones
        else escrow.reward_per_position
    )
    if not Decimal(0) < amount < open_value:
        raise ValidationFailed(
            "A split pays the contributor more than nothing and less than their whole open reward.",
            details=[{"field": "contributor_amount", "message": f"Between 0 and {open_value}"}],
        )
    return amount


async def decorate_disputes(
    session: AsyncSession, pairs: Sequence[tuple[Any, Any]], escrows: dict[uuid.UUID, Any] | None = None
) -> None:
    """Adds the arbiter threshold, the confirmed approvals of the current round and the split amount. Pass the
    escrows already loaded for a list; approvals are only looked up for v2 escrows that took votes."""
    if not pairs:
        return
    from app.modules.escrow.models import DisputeVote

    if escrows is None:
        escrows = await bounty_repo.escrows(session, list({d.bounty_id for d, _ in pairs}))
    ids = [
        d.id
        for d, _ in pairs
        if (e := escrows.get(d.bounty_id)) is not None and e.contract_version >= 2 and e.dispute_round > 0
    ]
    rows = (
        (await session.scalars(select(DisputeVote).where(DisputeVote.dispute_id.in_(ids)))).all()
        if ids
        else []
    )
    for dispute, out in pairs:
        escrow = escrows.get(dispute.bounty_id)
        round_ = escrow.dispute_round if escrow is not None else 0
        amount = dispute.contributor_amount
        out.contract_version = escrow.contract_version if escrow is not None else 1
        out.arbiter_threshold = escrow.arbiter_threshold if escrow is not None else 1
        out.contributor_amount = amount
        out.arbiter_approvals = sum(1 for v in rows if v.dispute_id == dispute.id and v.round == round_)
        if (
            out.escrow_frozen_onchain
            and dispute.resolution is not None
            and dispute.resolution.value == "SPLIT"
        ):
            out.requires_onchain_execution = True
