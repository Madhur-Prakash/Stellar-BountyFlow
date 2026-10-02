"""Escrow v2 chain actions: planning and verified settlement, plugged into the payments pipeline.

The payments service (``app/modules/payments/service.py``) owns prepare → sign → submit → verify. This module
adds the v2 actions to it:

| Action | Contract function | Signer | Settles after verification |
|---|---|---|---|
| ``MILESTONE_PAYOUT`` | ``release_milestone`` | requester | the milestone's payment and milestone row |
| ``BATCH_PAYOUT`` | ``batch_release`` | requester | every leg, only if every leg reads as paid on-chain |
| ``SUBMIT_WORK`` | ``submit_work`` | assigned contributor | the submission's review clock |
| ``REQUEST_CHANGES`` | ``request_changes`` | requester | clock stopped; the submission's revision request |
| ``REJECT_SUBMISSION`` | ``reject_submission`` | requester | clock stopped; the submission's rejection |
| ``CLAIM`` | ``claim`` | assigned contributor | the payment, once the contract reports it paid |
| ``DISPUTE_VOTE`` | ``vote_resolution`` | an arbiter (staff) | the vote mirror, and the resolution once executed |

Every settlement reads the contract back first: nothing is marked paid, answered or voted from a client claim.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain import soroban
from app.blockchain.soroban import ContractCall, EscrowSnapshot, PayoutLeg, ReviewSnapshot, VoteSnapshot
from app.blockchain.transactions import get_adapter
from app.cache.invalidation import invalidate_profile
from app.core.exceptions import Conflict, Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.money import ZERO, fmt, from_stroops, to_stroops
from app.core.rbac import Permission, has_permission
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.disputes.models import Dispute, DisputeResolution, DisputeStatus
from app.modules.escrow import milestones as milestone_service
from app.modules.escrow import review_clock
from app.modules.escrow.config import contract_version, escrow_settings
from app.modules.escrow.models import BountyMilestone, DisputeVote, MilestoneStatus
from app.modules.payments.models import (
    BlockchainTransaction,
    BountyEscrow,
    EscrowState,
    PaymentRecord,
    PaymentStatus,
    TxStatus,
    TxType,
)
from app.modules.payments.schemas import ChainAction, PrepareRequest
from app.modules.submissions.models import BountySubmission, OnchainReviewState, SubmissionStatus
from app.modules.users.models import User

if TYPE_CHECKING:
    from app.modules.payments.service import _Plan

logger = get_logger(__name__)

V2_ACTIONS = frozenset(
    {
        ChainAction.MILESTONE_PAYOUT,
        ChainAction.BATCH_PAYOUT,
        ChainAction.SUBMIT_WORK,
        ChainAction.REQUEST_CHANGES,
        ChainAction.REJECT_SUBMISSION,
        ChainAction.CLAIM,
        ChainAction.DISPUTE_VOTE,
    }
)
V2_TX_TYPES = frozenset(
    {
        TxType.MILESTONE_PAYOUT,
        TxType.BATCH_PAYOUT,
        TxType.SUBMIT_WORK,
        TxType.REQUEST_CHANGES,
        TxType.REJECT_SUBMISSION,
        TxType.CLAIM,
        TxType.DISPUTE_VOTE,
    }
)
# Transactions whose payment records follow the transaction (SIGNATURE_REQUIRED -> SUBMITTED -> CONFIRMED/FAILED).
PAYOUT_TX_TYPES = frozenset({TxType.MILESTONE_PAYOUT, TxType.BATCH_PAYOUT})
# Transactions after which the bounty's derived status (FUNDED / IN_PROGRESS / UNDER_REVIEW) is recomputed.
RECOMPUTE_TX_TYPES = (
    TxType.MILESTONE_PAYOUT,
    TxType.BATCH_PAYOUT,
    TxType.CLAIM,
    TxType.REQUEST_CHANGES,
    TxType.REJECT_SUBMISSION,
    TxType.DISPUTE_VOTE,
)

PENDING_REVIEW = (SubmissionStatus.SUBMITTED, SubmissionStatus.RESUBMITTED)
_V1_ONLY = "This bounty's escrow was created on the v1 contract, which has no {feature}."


def _now_ts() -> int:
    return int(utcnow().timestamp())


def _payments() -> Any:
    from app.modules.payments import service as payments

    return payments


def _require_v2(escrow: BountyEscrow, feature: str) -> None:
    if escrow.contract_version < 2:
        raise InvalidStateTransition(_V1_ONLY.format(feature=feature))


async def _snapshot(session: AsyncSession, escrow: BountyEscrow) -> EscrowSnapshot:
    snapshot, trusted = await _payments()._read_trusted_snapshot(session, escrow)
    if snapshot is None or not trusted:
        raise InvalidStateTransition("The escrow could not be read from the contract.")
    return snapshot


async def read_review(escrow: BountyEscrow, contributor: str) -> ReviewSnapshot | None:
    call = soroban.on_contract(
        soroban.review(bytes.fromhex(escrow.onchain_bounty_id), contributor), escrow.contract_id
    )
    return soroban.decode_review(await get_adapter().read(call))


async def read_votes(escrow: BountyEscrow) -> list[VoteSnapshot]:
    call = soroban.on_contract(
        soroban.resolution_votes(bytes.fromhex(escrow.onchain_bounty_id)), escrow.contract_id
    )
    return soroban.decode_votes(await get_adapter().read(call))


async def _submission(
    session: AsyncSession, bounty: Bounty, submission_id: uuid.UUID | None
) -> BountySubmission:
    submission = await session.get(BountySubmission, submission_id) if submission_id else None
    if submission is None or submission.bounty_id != bounty.id:
        raise NotFound("Submission not found.")
    return submission


async def _flush_before_lock(session: AsyncSession) -> None:
    """Locking reads refresh the locked rows (``populate_existing``), including rows they join; changes made
    earlier in this transaction are flushed first so the refresh can never undo them (the session does not
    autoflush). Nothing is committed here."""
    await session.flush()


async def _lock_submission(session: AsyncSession, submission_id: uuid.UUID | None) -> BountySubmission | None:
    if submission_id is None:
        return None
    await _flush_before_lock(session)
    return await session.scalar(
        select(BountySubmission)
        .where(BountySubmission.id == submission_id)
        .with_for_update(of=BountySubmission)
        .execution_options(populate_existing=True)
    )


async def _milestone(session: AsyncSession, submission: BountySubmission) -> BountyMilestone | None:
    return await session.get(BountyMilestone, submission.milestone_id) if submission.milestone_id else None


async def _locked_contributor(session: AsyncSession, assignment: BountyAssignment) -> str:
    """The contributor address the contract knows (confirmed ASSIGN)."""
    locked = await _payments()._assigned_address(session, assignment) if assignment.onchain_assigned else None
    if not locked:
        raise InvalidStateTransition(
            "The contributor is not assigned on-chain yet. The requester records the assignment first."
        )
    return str(locked)


# --- Creation terms -------------------------------------------------------------------------------


def review_window_for(bounty: Bounty) -> int:
    return bounty.review_window_seconds or escrow_settings().default_review_window


async def creation_call(
    session: AsyncSession,
    bounty: Bounty,
    escrow: BountyEscrow,
    *,
    requester: str,
    token: str,
    reward_stroops: int,
    deadline: int,
    deposit_stroops: int,
) -> ContractCall:
    """``create_escrow`` for plain terms (one arbiter, the default window, no milestones), else ``create_escrow_v2``.
    The chosen terms are stored on the escrow row; they become immutable on-chain with this call."""
    config = escrow_settings()
    milestones = [m.amount for m in await milestone_service.for_bounty(session, bounty.id)]
    window = review_window_for(bounty)
    bid = bytes.fromhex(escrow.onchain_bounty_id)
    if not config.arbiters:
        raise InvalidStateTransition("No dispute arbiter is configured (STELLAR_ARBITER_ADDRESS).")
    if escrow.contract_version < 2:
        if milestones or config.is_multisig or window != soroban.DEFAULT_REVIEW_WINDOW:
            raise InvalidStateTransition(
                "This bounty's escrow contract (v1) supports neither milestones, a review window other than "
                "7 days nor several arbiters."
            )
        return soroban.create_escrow(
            requester,
            bid,
            token,
            reward_stroops,
            bounty.positions_available,
            config.arbiters[0],
            deadline,
            deposit_stroops,
        )
    if requester in config.arbiters:
        raise ValidationFailed("An arbiter wallet cannot fund bounties.")
    escrow.arbiter_addresses = list(config.arbiters)
    escrow.arbiter_threshold = config.threshold
    escrow.review_window_seconds = window
    escrow.arbiter_address = config.arbiters[0]
    if not milestones and not config.is_multisig and window == soroban.DEFAULT_REVIEW_WINDOW:
        return soroban.create_escrow(
            requester,
            bid,
            token,
            reward_stroops,
            bounty.positions_available,
            config.arbiters[0],
            deadline,
            deposit_stroops,
        )
    terms = soroban.EscrowTerms(
        reward_per_position=reward_stroops,
        positions=bounty.positions_available,
        deadline=deadline,
        initial_deposit=deposit_stroops,
        arbiters=config.arbiters,
        threshold=config.threshold,
        review_window=window,
        milestones=tuple(to_stroops(amount) for amount in milestones),
    )
    return soroban.create_escrow_v2(requester, bid, token, terms)


async def adopt_configured_contract(session: AsyncSession, bounty: Bounty, escrow: BountyEscrow) -> None:
    """An escrow row that never reached the chain may still point at an earlier deployment (rows created before the
    v2 contract). Before its first funding it moves to the configured contract, with a fresh escrow id so a stale
    prepared transaction for the old contract can never be confused with it. Rows with anything on-chain stay."""
    config = escrow_settings()
    if (
        escrow.state != EscrowState.NOT_CREATED
        or not config.contract_id
        or escrow.contract_id == config.contract_id
    ):
        return
    payments = _payments()
    if await payments._in_flight(session, bounty.id, (TxType.ESCROW_CREATE, TxType.ESCROW_FUND)):
        return
    confirmed = await session.scalar(
        select(BlockchainTransaction.id).where(
            BlockchainTransaction.bounty_id == bounty.id,
            BlockchainTransaction.transaction_type.in_([TxType.ESCROW_CREATE, TxType.ESCROW_FUND]),
            BlockchainTransaction.status == TxStatus.CONFIRMED,
        )
    )
    if confirmed is not None:
        return
    if (
        await get_adapter().read_escrow(bytes.fromhex(escrow.onchain_bounty_id), escrow.contract_id)
        is not None
    ):
        return  # something exists on the old contract: keep serving it there
    previous = escrow.contract_id
    escrow.contract_id = config.contract_id
    escrow.contract_version = await contract_version()
    escrow.onchain_bounty_id = soroban.new_onchain_bounty_id(bounty.id).hex()
    logger.info("escrow_moved_to_configured_contract", bounty_id=str(bounty.id), previous=previous)


async def new_row_values() -> dict[str, Any]:
    """Escrow v2 columns of a new ``bounty_escrows`` row (the configured deployment)."""
    config = escrow_settings()
    return {
        "contract_version": await contract_version(),
        "arbiter_addresses": list(config.arbiters),
        "arbiter_threshold": config.threshold,
    }


# --- Guards for v1 actions ------------------------------------------------------------------------


async def guard_payout(session: AsyncSession, bounty: Bounty) -> None:
    """A milestone bounty is paid milestone by milestone (MILESTONE_PAYOUT / BATCH_PAYOUT)."""
    if await milestone_service.for_bounty(session, bounty.id):
        raise InvalidStateTransition(
            "This bounty is paid per milestone. Release the approved milestone instead."
        )


def guard_resolve(escrow: BountyEscrow) -> None:
    if escrow.arbiter_threshold > 1:
        raise InvalidStateTransition(
            f"This escrow needs {escrow.arbiter_threshold} arbiter approvals. Each arbiter signs a vote instead."
        )


# --- Planning -----------------------------------------------------------------------------------


async def plan(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> _Plan:
    action = req.action
    if action == ChainAction.MILESTONE_PAYOUT:
        return await _plan_milestone_payout(session, user, bounty, req, escrow, wallet)
    if action == ChainAction.BATCH_PAYOUT:
        return await _plan_batch(session, user, bounty, req, escrow, wallet)
    if action == ChainAction.SUBMIT_WORK:
        return await _plan_submit_work(session, user, bounty, req, escrow, wallet)
    if action in (ChainAction.REQUEST_CHANGES, ChainAction.REJECT_SUBMISSION):
        return await _plan_answer(session, user, bounty, req, escrow, wallet)
    if action == ChainAction.CLAIM:
        return await _plan_claim(session, user, bounty, req, escrow, wallet)
    if action == ChainAction.DISPUTE_VOTE:
        return await _plan_vote(session, user, bounty, req, escrow, wallet)
    raise ValidationFailed(f"Unsupported action {action}.")


def _require_requester(bounty: Bounty, user: User, escrow: BountyEscrow, wallet: str) -> None:
    payments = _payments()
    payments._require_owner(bounty, user)
    payments._require_requester_wallet(escrow, wallet)


async def _payable(session: AsyncSession, submission: BountySubmission) -> PaymentRecord:
    if submission.status != SubmissionStatus.APPROVED:
        raise InvalidStateTransition("Only approved submissions can be paid.")
    payment = await session.scalar(select(PaymentRecord).where(PaymentRecord.submission_id == submission.id))
    if payment is None:
        raise NotFound("Payment record not found.")
    if payment.payment_status in (PaymentStatus.SUBMITTED, PaymentStatus.CONFIRMED):
        raise Conflict("This payout has already been submitted.")
    return payment


async def _plan_milestone_payout(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> _Plan:
    payments = _payments()
    _require_requester(bounty, user, escrow, wallet)
    _require_v2(escrow, "milestones")
    if bounty.status == BountyStatus.DISPUTED:
        raise InvalidStateTransition("Payouts are frozen while a dispute is open.")
    submission = await _submission(session, bounty, req.submission_id)
    milestone = await _milestone(session, submission)
    if milestone is None:
        raise InvalidStateTransition("This submission is not for a milestone.")
    await _payable(session, submission)  # approved and not paid yet
    if escrow.state != EscrowState.FUNDED:
        raise InvalidStateTransition(
            "The escrow is not in a funded state, so the milestone cannot be released."
        )
    if milestone.status != MilestoneStatus.OPEN:
        raise Conflict("This milestone has already been paid.")
    assignment = await session.get(BountyAssignment, submission.assignment_id)
    assert assignment is not None
    contributor = await payments._contributor_address(session, assignment)
    call = soroban.release_milestone(
        wallet, bytes.fromhex(escrow.onchain_bounty_id), contributor, milestone.position
    )
    plan = payments._Plan(
        call,
        TxType.MILESTONE_PAYOUT,
        f"Release {payments._money(milestone.amount, escrow)} for the milestone “{milestone.title}”.",
        amount=milestone.amount,
        destination=contributor,
        submission_id=submission.id,
        assignment_id=assignment.id,
    )
    plan.metadata = {"milestone_id": str(milestone.id), "milestone": milestone.position}
    return plan


async def _plan_batch(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> _Plan:
    payments = _payments()
    _require_requester(bounty, user, escrow, wallet)
    _require_v2(escrow, "batch payouts")
    if bounty.status == BountyStatus.DISPUTED:
        raise InvalidStateTransition("Payouts are frozen while a dispute is open.")
    ids = list(dict.fromkeys(req.submission_ids or []))
    if not 2 <= len(ids) <= soroban.MAX_BATCH:
        raise ValidationFailed(
            f"Choose between 2 and {soroban.MAX_BATCH} approved submissions to pay together.",
            details=[{"field": "submission_ids", "message": "Between 2 and 10 submissions"}],
        )
    if escrow.state != EscrowState.FUNDED:
        raise InvalidStateTransition(
            "The escrow is not in a funded state, so the rewards cannot be released."
        )
    legs: list[PayoutLeg] = []
    recorded: list[dict[str, Any]] = []
    total = ZERO
    for submission_id in ids:
        submission = await _submission(session, bounty, submission_id)
        await _payable(session, submission)  # approved and not paid yet
        milestone = await _milestone(session, submission)
        assignment = await session.get(BountyAssignment, submission.assignment_id)
        assert assignment is not None
        contributor = await payments._contributor_address(session, assignment)
        if milestone is not None and milestone.status != MilestoneStatus.OPEN:
            raise Conflict(f"The milestone “{milestone.title}” has already been paid.")
        amount = milestone.amount if milestone is not None else bounty.reward_amount
        if milestone is None and any(
            leg.contributor == contributor and leg.milestone is None for leg in legs
        ):
            raise ValidationFailed("A contributor can be paid only once per bounty.")
        legs.append(PayoutLeg(contributor, milestone.position if milestone is not None else None))
        recorded.append(
            {
                "submission_id": str(submission.id),
                "assignment_id": str(assignment.id),
                "contributor": contributor,
                "milestone_id": str(milestone.id) if milestone is not None else None,
                "milestone": milestone.position if milestone is not None else None,
                "amount": fmt(amount),
            }
        )
        total += amount
    call = soroban.batch_release(wallet, bytes.fromhex(escrow.onchain_bounty_id), legs)
    plan = payments._Plan(
        call,
        TxType.BATCH_PAYOUT,
        f"Release {payments._money(total, escrow)} to {len(legs)} payments in one transaction.",
        amount=total,
    )
    plan.metadata = {"legs": recorded}
    return plan


async def _contributor_submission(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> tuple[BountySubmission, BountyAssignment, str]:
    submission = await _submission(session, bounty, req.submission_id)
    if submission.contributor_id != user.id:
        raise NotFound("Submission not found.")
    assignment = await session.get(BountyAssignment, submission.assignment_id)
    if assignment is None or assignment.status != AssignmentStatus.ACTIVE:
        raise InvalidStateTransition("Your assignment on this bounty is no longer active.")
    contributor = await _locked_contributor(session, assignment)
    if contributor != wallet:
        raise ValidationFailed("Sign with the wallet that was assigned on-chain.", code="wrong_wallet")
    return submission, assignment, contributor


async def _plan_submit_work(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> _Plan:
    payments = _payments()
    _require_v2(escrow, "review window")
    submission, assignment, contributor = await _contributor_submission(
        session, user, bounty, req, escrow, wallet
    )
    if submission.status not in PENDING_REVIEW:
        raise InvalidStateTransition("Only work that is waiting for review can be recorded on-chain.")
    review_clock.check_record(
        escrow.state, submission.onchain_state, now=_now_ts(), deadline=escrow.onchain_deadline
    )
    milestone = await _milestone(session, submission)
    if milestone is not None and milestone.status != MilestoneStatus.OPEN:
        raise InvalidStateTransition("This milestone has already been paid.")
    onchain = await read_review(escrow, contributor)
    if onchain is not None and onchain.state == "Pending":
        raise InvalidStateTransition("Work is already waiting for review on-chain.")
    if onchain is not None and onchain.state == "Rejected":
        raise InvalidStateTransition(
            "The requester rejected this work on-chain. Raise a dispute to continue."
        )
    window = escrow.review_window_seconds or review_window_for(bounty)
    call = soroban.submit_work(
        wallet, bytes.fromhex(escrow.onchain_bounty_id), milestone.position if milestone is not None else 0
    )
    days = max(1, round(window / 86_400))
    span = f"{days} day{'s' if days != 1 else ''}" if window >= 86_400 else f"{max(1, window // 60)} minutes"
    return payments._Plan(
        call,
        TxType.SUBMIT_WORK,
        f"Record your submission on-chain. The requester then has {span} to answer before you can claim.",
        destination=contributor,
        submission_id=submission.id,
        assignment_id=assignment.id,
    )


async def _opens_at(escrow: BountyEscrow, contributor: str) -> tuple[ReviewSnapshot, int]:
    onchain = await read_review(escrow, contributor)
    if onchain is None or onchain.state != "Pending":
        raise InvalidStateTransition("There is no submission waiting for review on-chain.")
    window = escrow.review_window_seconds or 0
    return onchain, review_clock.effective_claimable_at(onchain.claimable_at, escrow.clock_reset_at, window)


async def _plan_answer(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> _Plan:
    payments = _payments()
    _require_requester(bounty, user, escrow, wallet)
    _require_v2(escrow, "review window")
    submission = await _submission(session, bounty, req.submission_id)
    if submission.status not in PENDING_REVIEW:
        raise InvalidStateTransition(f"A {submission.status.value.lower()} submission cannot be reviewed.")
    if not req.feedback or len(req.feedback.strip()) < 5:
        raise ValidationFailed(
            "Tell the contributor what to change.", details=[{"field": "feedback", "message": "Required"}]
        )
    assignment = await session.get(BountyAssignment, submission.assignment_id)
    assert assignment is not None
    contributor = await _locked_contributor(session, assignment)
    _, opens_at = await _opens_at(escrow, contributor)
    review_clock.check_answer(escrow.state, submission.onchain_state, now=_now_ts(), opens_at=opens_at)
    bid = bytes.fromhex(escrow.onchain_bounty_id)
    if req.action == ChainAction.REQUEST_CHANGES:
        call = soroban.request_changes(wallet, bid, contributor)
        tx_type, description = (
            TxType.REQUEST_CHANGES,
            "Ask for changes on-chain. This stops the review clock.",
        )
    else:
        call = soroban.reject_submission(wallet, bid, contributor)
        tx_type, description = (
            TxType.REJECT_SUBMISSION,
            "Reject the submission on-chain. The contributor can still raise a dispute.",
        )
    plan = payments._Plan(
        call,
        tx_type,
        description,
        destination=contributor,
        submission_id=submission.id,
        assignment_id=assignment.id,
    )
    plan.metadata = {"feedback": req.feedback.strip()}
    return plan


async def _plan_claim(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> _Plan:
    payments = _payments()
    _require_v2(escrow, "review window")
    submission, assignment, contributor = await _contributor_submission(
        session, user, bounty, req, escrow, wallet
    )
    onchain, opens_at = await _opens_at(escrow, contributor)
    review_clock.check_claim(escrow.state, submission.onchain_state, now=_now_ts(), opens_at=opens_at)
    milestone = await _milestone(session, submission)
    snapshot = await _snapshot(session, escrow)
    if snapshot.milestones:
        amount = from_stroops(snapshot.milestones[onchain.milestone][0])
    else:
        amount = from_stroops(snapshot.reward_per_position)
    what = f"the milestone “{milestone.title}”" if milestone is not None else "your reward"
    plan = payments._Plan(
        call=soroban.claim(wallet, bytes.fromhex(escrow.onchain_bounty_id)),
        tx_type=TxType.CLAIM,
        description=f"Claim {payments._money(amount, escrow)} for {what}. The review window passed unanswered.",
        amount=amount,
        destination=contributor,
        submission_id=submission.id,
        assignment_id=assignment.id,
    )
    plan.metadata = {"milestone": onchain.milestone if snapshot.milestones else None}
    return plan


def resolution_amount(dispute: Dispute, snapshot: EscrowSnapshot) -> int:
    """Stroops the recorded resolution pays the contributor."""
    if dispute.resolution == DisputeResolution.RELEASE_TO_CONTRIBUTOR:
        return snapshot.position_value()
    if dispute.resolution == DisputeResolution.REFUND_TO_REQUESTER:
        return 0
    if dispute.resolution == DisputeResolution.SPLIT and dispute.contributor_amount is not None:
        return to_stroops(dispute.contributor_amount)
    raise InvalidStateTransition("Record a release, refund or split decision before arbiters vote on it.")


async def disputed_assignment(session: AsyncSession, dispute: Dispute) -> BountyAssignment | None:
    return await session.scalar(
        select(BountyAssignment).where(
            BountyAssignment.bounty_id == dispute.bounty_id,
            BountyAssignment.contributor_id == dispute.contributor_id,
            BountyAssignment.status == AssignmentStatus.ACTIVE,
        )
    )


async def _plan_vote(
    session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest, escrow: BountyEscrow, wallet: str
) -> _Plan:
    payments = _payments()
    if not has_permission(user, Permission.DISPUTE_RESOLVE):
        raise Forbidden("Only moderators can vote on dispute resolutions.")
    _require_v2(escrow, "arbiter set")
    dispute = await session.get(Dispute, req.dispute_id) if req.dispute_id else None
    if dispute is None or dispute.bounty_id != bounty.id:
        raise NotFound("Dispute not found.")
    if user.id in (dispute.raised_by_id, dispute.contributor_id, bounty.requester_id):
        raise Forbidden("You cannot vote on a dispute you are party to.")
    if escrow.state != EscrowState.DISPUTED:
        raise InvalidStateTransition("The escrow is not frozen on-chain; no arbiter vote is needed.")
    snapshot = await _snapshot(session, escrow)
    if wallet not in snapshot.arbiter_set:
        raise ValidationFailed("Sign with one of this escrow's arbiter wallets.", code="wrong_wallet")
    other = await session.scalar(
        select(DisputeVote.arbiter_address).where(
            DisputeVote.dispute_id == dispute.id,
            DisputeVote.voter_id == user.id,
            DisputeVote.round == snapshot.dispute_round,
            DisputeVote.arbiter_address != wallet,
        )
    )
    if other is not None:
        raise Forbidden("You already approved this resolution with another arbiter wallet.")
    assignment = await disputed_assignment(session, dispute)
    if assignment is None:
        raise InvalidStateTransition("The disputed contributor is not assigned on-chain.")
    contributor = await _locked_contributor(session, assignment)
    amount = resolution_amount(dispute, snapshot)
    if amount > snapshot.position_value():
        raise ValidationFailed("The split pays more than the contributor's open reward on this escrow.")
    call = soroban.vote_resolution(wallet, bytes.fromhex(escrow.onchain_bounty_id), contributor, amount)
    paid = from_stroops(amount)
    rest = from_stroops(snapshot.position_value() - amount)
    description = (
        f"Approve paying {payments._money(paid, escrow)} to the contributor"
        + (f" and returning {payments._money(rest, escrow)} to the requester." if rest > ZERO else ".")
        if amount
        else "Approve releasing the contributor's claim, so the requester can refund."
    )
    plan = payments._Plan(
        call,
        TxType.DISPUTE_VOTE,
        description,
        amount=paid if amount else None,
        destination=contributor,
        assignment_id=assignment.id,
        dispute_id=dispute.id,
    )
    plan.metadata = {"round": snapshot.dispute_round, "contributor_amount": amount}
    return plan


# --- Transaction lifecycle hooks --------------------------------------------------------------------
#
# Database discipline: each hook runs inside the one transaction of the payments step that calls it (prepare,
# submit, verify, sweep) and never commits itself. Rows are locked bounty first, then dependents in id order, and no
# row lock is held across network I/O: everything read from the chain for a settlement is read beforehand
# (``read_for_settlement``) and the verified result is written in the verification's single transaction.


def _leg_submission_ids(tx: BlockchainTransaction) -> list[uuid.UUID]:
    legs = (tx.verification_metadata or {}).get("legs") or []
    return [uuid.UUID(str(leg["submission_id"])) for leg in legs]


def _payment_submission_ids(tx: BlockchainTransaction) -> list[uuid.UUID]:
    if tx.transaction_type == TxType.BATCH_PAYOUT:
        return _leg_submission_ids(tx)
    if tx.transaction_type == TxType.MILESTONE_PAYOUT and tx.submission_id:
        return [tx.submission_id]
    return []


async def _lock_payments(
    session: AsyncSession, bounty_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[PaymentRecord]:
    """Locks the bounty, then the payment rows of ``ids`` in id order (deterministic, so batches never deadlock)."""
    await _flush_before_lock(session)
    await session.scalar(select(Bounty.id).where(Bounty.id == bounty_id).with_for_update(of=Bounty))
    rows = await session.scalars(
        select(PaymentRecord)
        .where(PaymentRecord.submission_id.in_(ids))
        .order_by(PaymentRecord.id)
        .with_for_update(of=PaymentRecord)
        .execution_options(populate_existing=True)
    )
    return list(rows.unique().all())


async def after_prepare(session: AsyncSession, tx: BlockchainTransaction) -> None:
    """Records the prepared payout on its payment rows, all or nothing: if any of them was paid or submitted in the
    meantime (a second tab), the whole prepare is refused and rolled back."""
    ids = _payment_submission_ids(tx)
    if not ids or tx.bounty_id is None:
        return
    payments = await _lock_payments(session, tx.bounty_id, ids)
    if len(payments) != len(ids) or any(
        p.payment_status in (PaymentStatus.SUBMITTED, PaymentStatus.CONFIRMED) for p in payments
    ):
        raise Conflict("One of these payouts has already been submitted.")
    for payment in payments:
        payment.payment_status = PaymentStatus.SIGNATURE_REQUIRED
        payment.blockchain_transaction_id = tx.id


async def on_submitted(session: AsyncSession, tx: BlockchainTransaction) -> None:
    ids = _payment_submission_ids(tx)
    if ids and tx.bounty_id is not None:
        for payment in await _lock_payments(session, tx.bounty_id, ids):
            payment.payment_status = PaymentStatus.SUBMITTED
            payment.blockchain_transaction_id = tx.id


async def on_failure(session: AsyncSession, tx: BlockchainTransaction) -> None:
    ids = _payment_submission_ids(tx)
    if ids and tx.bounty_id is not None:
        for payment in await _lock_payments(session, tx.bounty_id, ids):
            if payment.payment_status in (PaymentStatus.SIGNATURE_REQUIRED, PaymentStatus.SUBMITTED):
                payment.payment_status = PaymentStatus.FAILED


async def on_expired(session: AsyncSession, tx: BlockchainTransaction) -> None:
    """An unsigned payout that expired leaves its payments payable again."""
    ids = _payment_submission_ids(tx)
    if ids and tx.bounty_id is not None:
        for payment in await _lock_payments(session, tx.bounty_id, ids):
            if payment.payment_status == PaymentStatus.SIGNATURE_REQUIRED:
                payment.payment_status = PaymentStatus.CREATED


async def after_snapshot(
    session: AsyncSession,
    bounty: Bounty,
    snapshot: EscrowSnapshot | None,
    tx: BlockchainTransaction | None,
) -> list[BountyMilestone]:
    """Mirrors the milestones' paid flags from a trusted snapshot (every verified transaction and reconcile).
    The caller holds the bounty lock; the milestone rows are locked here."""
    return await milestone_service.sync_from_snapshot(session, bounty.id, snapshot, tx)


@dataclass
class SettlementReads:
    """Contract state a confirmed v2 transaction is settled from, read before any row lock is taken."""

    review: ReviewSnapshot | None = None  # the destination contributor's review
    votes: list[VoteSnapshot] = field(default_factory=list)  # current-round votes (DISPUTE_VOTE)
    assignments: dict[str, str | None] = field(
        default_factory=dict
    )  # contributor -> "Assigned" | "Paid" | None


async def read_for_settlement(escrow: BountyEscrow, tx: BlockchainTransaction) -> SettlementReads | None:
    """Reads everything the settlement of ``tx`` needs from the contract (network I/O, no locks held)."""
    if tx.transaction_type not in V2_TX_TYPES:
        return None
    reads = SettlementReads()
    bid = bytes.fromhex(escrow.onchain_bounty_id)
    contributors = [str(leg["contributor"]) for leg in (tx.verification_metadata or {}).get("legs") or []]
    if tx.destination_address:
        contributors.append(tx.destination_address)
        if tx.transaction_type in (
            TxType.SUBMIT_WORK,
            TxType.REQUEST_CHANGES,
            TxType.REJECT_SUBMISSION,
            TxType.CLAIM,
        ):
            reads.review = await read_review(escrow, tx.destination_address)
    for contributor in dict.fromkeys(contributors):
        reads.assignments[contributor] = await get_adapter().read_assignment(
            bid, contributor, escrow.contract_id
        )
    if tx.transaction_type == TxType.DISPUTE_VOTE:
        reads.votes = await read_votes(escrow)
    return reads


async def on_success(
    session: AsyncSession,
    bounty: Bounty,
    escrow: BountyEscrow,
    snapshot: EscrowSnapshot | None,
    tx: BlockchainTransaction,
    reads: SettlementReads | None,
) -> None:
    """Settles a confirmed v2 transaction from the contract state it produced (read beforehand). Runs inside the
    verification's transaction with the bounty and escrow rows already locked."""
    reads = reads or SettlementReads()
    if tx.transaction_type == TxType.SUBMIT_WORK:
        await _settle_submit_work(session, bounty, escrow, tx, reads)
    elif tx.transaction_type in (TxType.REQUEST_CHANGES, TxType.REJECT_SUBMISSION):
        await _settle_answer(session, bounty, tx, reads)
    elif tx.transaction_type == TxType.MILESTONE_PAYOUT:
        await _settle_milestone_payout(session, bounty, snapshot, tx, reads)
    elif tx.transaction_type == TxType.BATCH_PAYOUT:
        await _settle_batch(session, bounty, snapshot, tx, reads)
    elif tx.transaction_type == TxType.CLAIM:
        await _settle_claim(session, bounty, snapshot, tx, reads)
    elif tx.transaction_type == TxType.DISPUTE_VOTE:
        await _settle_vote(session, bounty, escrow, snapshot, tx, reads)


async def _settle_submit_work(
    session: AsyncSession,
    bounty: Bounty,
    escrow: BountyEscrow,
    tx: BlockchainTransaction,
    reads: SettlementReads,
) -> None:
    submission = await _lock_submission(session, tx.submission_id)
    onchain = reads.review
    if submission is None:
        return
    if onchain is None or onchain.state != "Pending":
        logger.error(
            "submission_not_reflected_on_chain", tx_id=str(tx.id), state=onchain.state if onchain else None
        )
        return
    opens_at = review_clock.effective_claimable_at(
        onchain.claimable_at, escrow.clock_reset_at, escrow.review_window_seconds or 0
    )
    submission.onchain_state = OnchainReviewState.PENDING
    submission.onchain_submitted_at = review_clock.to_datetime(onchain.submitted_at)
    submission.claimable_at = review_clock.to_datetime(opens_at)
    submission.claim_notified_at = None
    add_event(
        session,
        event_type=EventType.SUBMISSION_ONCHAIN_RECORDED,
        aggregate_type="submission",
        aggregate_id=submission.id,
        actor_id=tx.user_id,
        payload={
            **_submission_payload(submission, bounty),
            "claimable_at": submission.claimable_at.isoformat(),
        },
    )


def _submission_payload(submission: BountySubmission, bounty: Bounty) -> dict[str, Any]:
    return {
        "submission_id": submission.id,
        "bounty_id": bounty.id,
        "requester_id": bounty.requester_id,
        "contributor_id": submission.contributor_id,
        "title": bounty.title,
        "status": submission.status.value,
        "version": submission.version,
    }


async def _settle_answer(
    session: AsyncSession, bounty: Bounty, tx: BlockchainTransaction, reads: SettlementReads
) -> None:
    """The requester's on-chain answer is verified: mirror it and apply the same review in BountyFlow."""
    submission = await _lock_submission(session, tx.submission_id)
    if submission is None:
        return
    onchain = reads.review
    expected = "ChangesRequested" if tx.transaction_type == TxType.REQUEST_CHANGES else "Rejected"
    if onchain is None or onchain.state != expected:
        logger.error(
            "review_answer_not_reflected_on_chain", tx_id=str(tx.id), state=onchain.state if onchain else None
        )
        return
    submission.onchain_state = review_clock.FROM_CHAIN[expected]
    submission.claimable_at = None
    if submission.status not in PENDING_REVIEW:
        return
    feedback = str((tx.verification_metadata or {}).get("feedback") or "")
    rejected = tx.transaction_type == TxType.REJECT_SUBMISSION
    submission.status = SubmissionStatus.REJECTED if rejected else SubmissionStatus.REVISION_REQUESTED
    submission.review_feedback = feedback or None
    submission.reviewer_id = tx.user_id
    submission.reviewed_at = utcnow()
    # A rejected contributor stays assigned on-chain until a dispute or their consent, so the assignment stays
    # active here too (they can still raise a dispute).
    audit.record(
        session,
        actor_id=tx.user_id,
        action="submission.rejected" if rejected else "submission.revision_requested",
        entity_type="submission",
        entity_id=submission.id,
        bounty_id=bounty.id,
        metadata={"version": submission.version, "onchain": True},
    )
    add_event(
        session,
        event_type=EventType.SUBMISSION_REJECTED if rejected else EventType.SUBMISSION_REVISION_REQUESTED,
        aggregate_type="submission",
        aggregate_id=submission.id,
        actor_id=tx.user_id,
        payload=_submission_payload(submission, bounty),
    )
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, tx.user_id)


async def _lock_payment(
    session: AsyncSession,
    bounty: Bounty,
    submission: BountySubmission,
    milestone: BountyMilestone | None,
    amount: Decimal,
) -> PaymentRecord:
    """The submission's payment row, locked. Created with an upsert when a claim or a dispute pays work that was
    never approved in BountyFlow, so a verification that runs twice can never insert it twice."""
    await _flush_before_lock(session)
    await session.execute(
        pg_insert(PaymentRecord)
        .values(
            id=uuid.uuid4(),
            bounty_id=bounty.id,
            contributor_id=submission.contributor_id,
            submission_id=submission.id,
            milestone_id=milestone.id if milestone else None,
            amount=amount,
            asset_identifier=bounty.reward_asset_identifier,
            payment_status=PaymentStatus.CREATED,
        )
        .on_conflict_do_nothing(index_elements=[PaymentRecord.submission_id])
    )
    payment = await session.scalar(
        select(PaymentRecord)
        .where(PaymentRecord.submission_id == submission.id)
        .with_for_update(of=PaymentRecord)
        .execution_options(populate_existing=True)
    )
    assert payment is not None
    return payment


async def _settle_leg(
    session: AsyncSession,
    bounty: Bounty,
    tx: BlockchainTransaction,
    *,
    submission: BountySubmission,
    amount: Decimal,
    milestone: BountyMilestone | None,
    position_complete: bool,
    approve_reason: str | None = None,
) -> None:
    """Records one verified payment: the payment record, the milestone, the submission and the assignment. The caller
    holds the bounty lock and has locked the submission; this locks the payment and the assignment."""
    now = utcnow()
    payment = await _lock_payment(session, bounty, submission, milestone, amount)
    if payment.payment_status == PaymentStatus.CONFIRMED:
        return  # settled by an earlier run of this verification
    payment.amount = amount
    payment.milestone_id = milestone.id if milestone else payment.milestone_id
    payment.payment_status = PaymentStatus.CONFIRMED
    payment.settled_at = now
    payment.blockchain_transaction_id = tx.id
    if milestone is not None and milestone.status == MilestoneStatus.OPEN:
        milestone.status = MilestoneStatus.PAID
        milestone.paid_at = tx.confirmed_at or now
        milestone.payout_transaction_id = tx.id
    if submission.onchain_state is not None:
        submission.onchain_state = OnchainReviewState.PAID
        submission.claimable_at = None
    if submission.status != SubmissionStatus.APPROVED:
        submission.status = SubmissionStatus.APPROVED
        submission.review_feedback = approve_reason
        submission.reviewed_at = now
    assignment = await session.get(BountyAssignment, submission.assignment_id, with_for_update=True)
    if position_complete and assignment is not None and assignment.status == AssignmentStatus.ACTIVE:
        assignment.status = AssignmentStatus.COMPLETED
        assignment.completed_at = now
    contributor = await session.get(User, submission.contributor_id)
    audit.record(
        session,
        actor_id=tx.user_id,
        action="payment.confirmed",
        entity_type="payment",
        entity_id=payment.id,
        bounty_id=bounty.id,
        metadata={
            "amount": fmt(amount),
            "hash": tx.transaction_hash,
            "contributor": contributor.username if contributor else None,
            **({"milestone": milestone.title} if milestone else {}),
            **({"claimed": True} if tx.transaction_type == TxType.CLAIM else {}),
        },
    )
    payload: dict[str, Any] = {
        "bounty_id": bounty.id,
        "requester_id": bounty.requester_id,
        "contributor_id": submission.contributor_id,
        "title": bounty.title,
        "amount": fmt(amount),
        "asset_code": bounty.reward_asset or "XLM",
        "transaction_id": tx.id,
    }
    if tx.transaction_type == TxType.CLAIM:
        payload["claimed"] = True
    if milestone is not None:
        add_event(
            session,
            event_type=EventType.MILESTONE_PAID,
            aggregate_type="payment",
            aggregate_id=payment.id,
            actor_id=tx.user_id,
            payload={**payload, "milestone_id": milestone.id, "milestone_title": milestone.title},
        )
    else:
        add_event(
            session,
            event_type=EventType.PAYMENT_CONFIRMED,
            aggregate_type="payment",
            aggregate_id=payment.id,
            actor_id=tx.user_id,
            payload=payload,
        )
    if contributor is not None:
        await invalidate_profile(contributor.username)


def _milestone_paid(snapshot: EscrowSnapshot, milestone: BountyMilestone) -> bool:
    return milestone.position < len(snapshot.milestones) and snapshot.milestones[milestone.position][1]


async def _settle_milestone_payout(
    session: AsyncSession,
    bounty: Bounty,
    snapshot: EscrowSnapshot | None,
    tx: BlockchainTransaction,
    reads: SettlementReads,
) -> None:
    submission = await _lock_submission(session, tx.submission_id)
    milestone = await _milestone(session, submission) if submission else None
    if submission is None or milestone is None or snapshot is None or not tx.destination_address:
        return
    if not _milestone_paid(snapshot, milestone):
        logger.error("payout_not_reflected_on_chain", tx_id=str(tx.id), milestone=milestone.position)
        return
    await _settle_leg(
        session,
        bounty,
        tx,
        submission=submission,
        amount=milestone.amount,
        milestone=milestone,
        position_complete=reads.assignments.get(tx.destination_address) == "Paid",
    )


async def _settle_batch(
    session: AsyncSession,
    bounty: Bounty,
    snapshot: EscrowSnapshot | None,
    tx: BlockchainTransaction,
    reads: SettlementReads,
) -> None:
    """Every leg is checked against the contract first; if any leg does not read as paid, nothing is marked paid.
    All of the batch's submissions and payments are locked up front, in id order, before anything changes."""
    legs = (tx.verification_metadata or {}).get("legs") or []
    if snapshot is None or not legs or tx.bounty_id is None:
        return
    ids = sorted(uuid.UUID(str(leg["submission_id"])) for leg in legs)
    await _flush_before_lock(session)
    submissions = {
        s.id: s
        for s in (
            await session.scalars(
                select(BountySubmission)
                .where(BountySubmission.id.in_(ids))
                .order_by(BountySubmission.id)
                .with_for_update(of=BountySubmission)
                .execution_options(populate_existing=True)
            )
        )
        .unique()
        .all()
    }
    await _lock_payments(session, tx.bounty_id, ids)
    verified: list[tuple[BountySubmission, BountyMilestone | None, Decimal, bool]] = []
    for leg in legs:
        submission = submissions.get(uuid.UUID(str(leg["submission_id"])))
        if submission is None:
            logger.error("batch_leg_missing", tx_id=str(tx.id), leg=leg)
            return
        milestone = await _milestone(session, submission)
        contributor = str(leg["contributor"])
        position_complete = reads.assignments.get(contributor) == "Paid"
        paid = _milestone_paid(snapshot, milestone) if milestone is not None else position_complete
        if not paid:
            logger.error("batch_leg_not_reflected_on_chain", tx_id=str(tx.id), contributor=contributor)
            return
        amount = milestone.amount if milestone is not None else bounty.reward_amount
        verified.append((submission, milestone, amount, position_complete))
    for submission, milestone, amount, position_complete in verified:
        await _settle_leg(
            session,
            bounty,
            tx,
            submission=submission,
            amount=amount,
            milestone=milestone,
            position_complete=position_complete,
        )


async def _settle_claim(
    session: AsyncSession,
    bounty: Bounty,
    snapshot: EscrowSnapshot | None,
    tx: BlockchainTransaction,
    reads: SettlementReads,
) -> None:
    submission = await _lock_submission(session, tx.submission_id)
    if submission is None or snapshot is None or not tx.destination_address:
        return
    milestone = await _milestone(session, submission)
    position_complete = reads.assignments.get(tx.destination_address) == "Paid"
    paid = _milestone_paid(snapshot, milestone) if milestone is not None else position_complete
    if not paid or reads.review is not None:
        logger.error("claim_not_reflected_on_chain", tx_id=str(tx.id))
        return
    await _settle_leg(
        session,
        bounty,
        tx,
        submission=submission,
        amount=milestone.amount if milestone is not None else (tx.amount or bounty.reward_amount),
        milestone=milestone,
        position_complete=position_complete,
        approve_reason="Paid by the contributor's claim after the review window passed.",
    )


async def _settle_vote(
    session: AsyncSession,
    bounty: Bounty,
    escrow: BountyEscrow,
    snapshot: EscrowSnapshot | None,
    tx: BlockchainTransaction,
    reads: SettlementReads,
) -> None:
    await _flush_before_lock(session)
    dispute = (
        await session.scalar(
            select(Dispute)
            .where(Dispute.id == tx.dispute_id)
            .with_for_update(of=Dispute)
            .execution_options(populate_existing=True)
        )
        if tx.dispute_id
        else None
    )
    if dispute is None or snapshot is None or not tx.destination_address:
        return
    meta = tx.verification_metadata or {}
    vote_round = int(meta.get("round", snapshot.dispute_round))
    amount = int(meta.get("contributor_amount", 0))
    executed = snapshot.status != "Disputed" or snapshot.dispute_round != vote_round
    if not executed:
        if not any(v.arbiter == tx.source_address and v.contributor_amount == amount for v in reads.votes):
            logger.error("vote_not_reflected_on_chain", tx_id=str(tx.id))
            return
        approvals = sum(
            1
            for v in reads.votes
            if v.contributor == tx.destination_address and v.contributor_amount == amount
        )
    else:
        approvals = snapshot.threshold
    await _record_vote(session, dispute, tx, vote_round, amount)
    add_event(
        session,
        event_type=EventType.DISPUTE_VOTE_RECORDED,
        aggregate_type="bounty",
        aggregate_id=bounty.id,
        actor_id=tx.user_id,
        payload={
            "bounty_id": bounty.id,
            "dispute_id": dispute.id,
            "requester_id": bounty.requester_id,
            "contributor_id": dispute.contributor_id,
            "title": bounty.title,
            "status": dispute.status.value,
            "approvals": approvals,
            "threshold": snapshot.threshold,
        },
    )
    if not executed:
        return
    # The approval that reached the threshold executed the resolution on-chain.
    state = reads.assignments.get(tx.destination_address)
    assignment = (
        await session.get(BountyAssignment, tx.assignment_id, with_for_update=True)
        if tx.assignment_id
        else None
    )
    submission = (
        await session.scalar(
            select(BountySubmission)
            .where(BountySubmission.assignment_id == assignment.id)
            .order_by(BountySubmission.created_at.desc())
            .limit(1)
            .with_for_update(of=BountySubmission)
        )
        if assignment is not None
        else None
    )
    payments = _payments()
    if state == "Paid" and amount > 0:
        if submission is not None:
            milestone = await _milestone(session, submission)
            await _settle_leg(
                session,
                bounty,
                tx,
                submission=submission,
                amount=from_stroops(amount),
                milestone=milestone,
                position_complete=True,
                approve_reason="Approved through dispute resolution.",
            )
            if milestone is not None and milestone.status == MilestoneStatus.PAID:
                milestone.status = MilestoneStatus.SETTLED
        elif assignment is not None:
            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = utcnow()
    elif state is None and assignment is not None:
        assignment.status = AssignmentStatus.RELEASED
        assignment.released_at = utcnow()
        assignment.onchain_assigned = False
        await payments._review_disputed_submission(session, tx, approved=False)
    if bounty.status == BountyStatus.DISPUTED and escrow.state != EscrowState.DISPUTED:
        await payments._restore_after_dispute(session, bounty, escrow)


async def _record_vote(
    session: AsyncSession, dispute: Dispute, tx: BlockchainTransaction, vote_round: int, amount: int
) -> None:
    """Upserts the vote mirror, so a verification that runs twice records the vote once."""
    values = {
        "voter_id": tx.user_id,
        "contributor_amount": from_stroops(amount),
        "transaction_id": tx.id,
    }
    await session.execute(
        pg_insert(DisputeVote)
        .values(
            id=uuid.uuid4(),
            dispute_id=dispute.id,
            bounty_id=dispute.bounty_id,
            arbiter_address=tx.source_address or "",
            round=vote_round,
            **values,
        )
        .on_conflict_do_update(constraint="uq_bountyflow_dispute_votes_arbiter_round", set_=values)
    )


# --- Reads for other modules ------------------------------------------------------------------------


def onchain_review_view(submission: BountySubmission, escrow: BountyEscrow | None) -> dict[str, Any] | None:
    """The submission's review clock as the API shows it (``OnchainReviewOut`` fields)."""
    if submission.onchain_state is None:
        return None
    now = utcnow()
    open_escrow = escrow is not None and escrow.state in review_clock.REVIEW_OPEN
    pending = submission.onchain_state == OnchainReviewState.PENDING
    due = submission.claimable_at
    return {
        "state": submission.onchain_state,
        "submitted_at": submission.onchain_submitted_at,
        "claimable_at": due,
        "can_claim": bool(pending and open_escrow and due is not None and now >= due),
        "can_answer": bool(pending and open_escrow and due is not None and now < due),
    }


async def dispute_votes(session: AsyncSession, dispute_id: uuid.UUID) -> list[DisputeVote]:
    rows = await session.scalars(
        select(DisputeVote).where(DisputeVote.dispute_id == dispute_id).order_by(DisputeVote.created_at)
    )
    return list(rows.all())


def is_open_dispute(dispute: Dispute) -> bool:
    return dispute.status in (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW)
