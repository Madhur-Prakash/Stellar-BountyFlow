"""Controlled dispute workflow.

Raising a dispute moves the bounty to DISPUTED, which freezes reviews and payouts in the application. Either party
may additionally freeze the on-chain escrow (chain action RAISE_DISPUTE); only then can the escrow's arbiter wallet
route the locked reward on-chain (RESOLVE_DISPUTE). The arbiter can never send funds anywhere except to the assigned
contributor, or release the contributor's claim so the requester can refund — there is no admin withdrawal.

If the escrow was NOT frozen on-chain, a moderator's resolution is an off-chain decision recorded here: the
application state is updated accordingly, but any payout still requires the requester's own wallet signature.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.rbac import Permission, ensure_permission, has_permission
from app.core.schemas import Page, PageParams
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties import state_machine as sm
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.bounties.schemas import ActivityBounty
from app.modules.disputes.models import Dispute, DisputeEvidence, DisputeResolution, DisputeStatus
from app.modules.disputes.schemas import DisputeCreate, DisputeOut, EvidenceCreate, EvidenceOut
from app.modules.payments.models import BountyEscrow, EscrowState, PaymentRecord, PaymentStatus
from app.modules.submissions.models import BountySubmission, SubmissionStatus
from app.modules.users.models import User

OPEN_STATES = (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW)


def serialize(d: Dispute, escrow: BountyEscrow | None, contributor: User | None) -> DisputeOut:
    frozen = escrow is not None and escrow.state == EscrowState.DISPUTED
    return DisputeOut(
        id=d.id,
        bounty=ActivityBounty(id=d.bounty.id, slug=d.bounty.slug, title=d.bounty.title),
        raised_by=bounty_service.user_summary(d.raised_by),
        contributor=bounty_service.user_summary(contributor) if contributor else None,
        reason=d.reason,
        status=d.status,
        assigned_moderator=bounty_service.user_summary(d.assigned_moderator)
        if d.assigned_moderator
        else None,
        resolution=d.resolution,
        resolution_note=d.resolution_note,
        evidence=[
            EvidenceOut(
                id=e.id,
                submitted_by=bounty_service.user_summary(e.submitted_by),
                description=e.description,
                url=e.url,
                created_at=e.created_at,
            )
            for e in d.evidence
        ],
        escrow_frozen_onchain=frozen,
        requires_onchain_execution=frozen
        and d.resolution in (DisputeResolution.RELEASE_TO_CONTRIBUTOR, DisputeResolution.REFUND_TO_REQUESTER),
        created_at=d.created_at,
        resolved_at=d.resolved_at,
    )


async def _out(session: AsyncSession, d: Dispute) -> DisputeOut:
    escrow = await bounty_repo.get_escrow(session, d.bounty_id)
    contributor = await session.get(User, d.contributor_id) if d.contributor_id else None
    return serialize(d, escrow, contributor)


async def _outs(session: AsyncSession, disputes: Sequence[Dispute]) -> list[DisputeOut]:
    """Batch serialization for lists: one query for all escrows and one for all contributors (no N+1)."""
    escrows = await bounty_repo.escrows(session, list({d.bounty_id for d in disputes}))
    contributor_ids = {d.contributor_id for d in disputes if d.contributor_id}
    contributors = (
        {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(contributor_ids)))).all()}
        if contributor_ids
        else {}
    )
    return [
        serialize(
            d, escrows.get(d.bounty_id), contributors.get(d.contributor_id) if d.contributor_id else None
        )
        for d in disputes
    ]


def _payload(d: Dispute, bounty: Bounty) -> dict[str, object]:
    return {
        "bounty_id": bounty.id,
        "dispute_id": d.id,
        "requester_id": bounty.requester_id,
        "contributor_id": d.contributor_id,
        "title": bounty.title,
        "status": d.status.value,
    }


def _is_party(d: Dispute, user: User) -> bool:
    return user.id in (d.raised_by_id, d.contributor_id, d.bounty.requester_id)


async def raise_dispute(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, data: DisputeCreate
) -> DisputeOut:
    ensure_permission(user, Permission.DISPUTE_RAISE)
    bounty = await bounty_service.load_for_update(session, bounty_id)
    if bounty.status not in sm.DISPUTABLE:
        raise InvalidStateTransition(
            "Disputes can only be raised while work is in progress, under review, or during a cancellation."
        )
    active = (
        (
            await session.scalars(
                select(BountyAssignment).where(
                    BountyAssignment.bounty_id == bounty.id,
                    BountyAssignment.status == AssignmentStatus.ACTIVE,
                )
            )
        )
        .unique()
        .all()
    )
    if user.id == bounty.requester_id:
        if data.contributor_id:
            target = next((a for a in active if a.contributor_id == data.contributor_id), None)
        else:
            target = active[0] if len(active) == 1 else None
        if target is None:
            raise ValidationFailed(
                "Choose which assigned contributor the dispute concerns.",
                details=[{"field": "contributor_id", "message": "Required"}],
            )
        contributor_id = target.contributor_id
    else:
        if not any(a.contributor_id == user.id for a in active):
            raise Forbidden("Only the requester or an assigned contributor can raise a dispute.")
        contributor_id = user.id
    dispute = Dispute(
        id=uuid.uuid4(),
        bounty_id=bounty.id,
        raised_by_id=user.id,
        contributor_id=contributor_id,
        reason=data.reason.strip(),
        status=DisputeStatus.OPEN,
        status_before=bounty.status.value,
    )
    session.add(dispute)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("There is already an open dispute for this bounty.") from exc
    if data.evidence_url:
        session.add(
            DisputeEvidence(
                dispute_id=dispute.id,
                submitted_by_id=user.id,
                description="Initial evidence",
                url=str(data.evidence_url),
            )
        )
    bounty.metadata_ = {**(bounty.metadata_ or {}), "status_before_dispute": bounty.status.value}
    bounty_service.change_status(session, bounty, BountyStatus.DISPUTED, actor_id=user.id)
    audit.record(
        session,
        actor_id=user.id,
        action="dispute.raised",
        entity_type="dispute",
        entity_id=dispute.id,
        bounty_id=bounty.id,
    )
    add_event(
        session,
        event_type=EventType.DISPUTE_RAISED,
        aggregate_type="bounty",
        aggregate_id=bounty.id,
        actor_id=user.id,
        payload=_payload(dispute, bounty),
    )
    await bounty_service.commit_bounty(session, bounty)
    return await get(session, user, dispute.id)


async def _load(session: AsyncSession, dispute_id: uuid.UUID, *, for_update: bool = False) -> Dispute:
    stmt = select(Dispute).where(Dispute.id == dispute_id)
    if for_update:
        stmt = stmt.with_for_update(of=Dispute).execution_options(populate_existing=True)
    d = await session.scalar(stmt)
    if d is None:
        raise NotFound("Dispute not found.")
    return d


async def get(session: AsyncSession, user: User, dispute_id: uuid.UUID) -> DisputeOut:
    d = await _load(session, dispute_id)
    await session.refresh(d, ["evidence"])
    if not (_is_party(d, user) or has_permission(user, Permission.DISPUTE_VIEW_ALL)):
        raise NotFound("Dispute not found.")
    return await _out(session, d)


async def mine(session: AsyncSession, user: User) -> list[DisputeOut]:
    rows = (
        (
            await session.scalars(
                select(Dispute)
                .join(Bounty, Bounty.id == Dispute.bounty_id)
                .where(
                    or_(
                        Dispute.raised_by_id == user.id,
                        Dispute.contributor_id == user.id,
                        Bounty.requester_id == user.id,
                    )
                )
                .order_by(Dispute.created_at.desc())
                .limit(100)
            )
        )
        .unique()
        .all()
    )
    return await _outs(session, rows)


async def list_all(
    session: AsyncSession, status: DisputeStatus | None, params: PageParams
) -> Page[DisputeOut]:
    base = select(Dispute)
    if status:
        base = base.where(Dispute.status == status)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(Dispute.created_at.desc()).offset(params.offset).limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[DisputeOut].build(await _outs(session, rows), total, params)


async def add_evidence(
    session: AsyncSession, user: User, dispute_id: uuid.UUID, data: EvidenceCreate
) -> DisputeOut:
    d = await _load(session, dispute_id, for_update=True)
    if not (_is_party(d, user) or has_permission(user, Permission.DISPUTE_RESOLVE)):
        raise NotFound("Dispute not found.")
    if d.status not in OPEN_STATES:
        raise InvalidStateTransition("Evidence can only be added to open disputes.")
    session.add(
        DisputeEvidence(
            dispute_id=d.id,
            submitted_by_id=user.id,
            description=data.description.strip(),
            url=str(data.url) if data.url else None,
        )
    )
    audit.record(
        session,
        actor_id=user.id,
        action="dispute.evidence_added",
        entity_type="dispute",
        entity_id=d.id,
        bounty_id=d.bounty_id,
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.DISPUTE_UPDATED,
        aggregate_type="bounty",
        aggregate_id=d.bounty_id,
        actor_id=user.id,
        payload=_payload(d, d.bounty),
    )
    await session.commit()
    return await get(session, user, d.id)


async def assign_self(session: AsyncSession, moderator: User, dispute_id: uuid.UUID) -> DisputeOut:
    ensure_permission(moderator, Permission.DISPUTE_RESOLVE)
    d = await _load(session, dispute_id, for_update=True)
    if d.status not in OPEN_STATES:
        raise InvalidStateTransition("This dispute is already closed.")
    if moderator.id in (d.raised_by_id, d.contributor_id, d.bounty.requester_id):
        raise Forbidden("You cannot moderate a dispute you are party to.")
    d.assigned_moderator_id = moderator.id
    d.status = DisputeStatus.UNDER_REVIEW
    audit.record(
        session,
        actor_id=moderator.id,
        action="dispute.assigned",
        entity_type="dispute",
        entity_id=d.id,
        bounty_id=d.bounty_id,
    )
    add_event(
        session,
        event_type=EventType.DISPUTE_UPDATED,
        aggregate_type="bounty",
        aggregate_id=d.bounty_id,
        actor_id=moderator.id,
        payload=_payload(d, d.bounty),
    )
    await session.commit()
    return await get(session, moderator, d.id)


async def resolve(
    session: AsyncSession, moderator: User, dispute_id: uuid.UUID, resolution: DisputeResolution, note: str
) -> DisputeOut:
    ensure_permission(moderator, Permission.DISPUTE_RESOLVE)
    bounty_id = (await _load(session, dispute_id)).bounty_id
    bounty = await bounty_service.load_for_update(session, bounty_id)  # lock order: bounty, then dispute
    d = await _load(session, dispute_id, for_update=True)
    if d.status not in OPEN_STATES:
        raise InvalidStateTransition("This dispute is already closed.")
    if moderator.id in (d.raised_by_id, d.contributor_id, bounty.requester_id):
        raise Forbidden("You cannot resolve a dispute you are party to.")
    escrow = await bounty_repo.get_escrow(session, bounty.id)
    frozen = escrow is not None and escrow.state == EscrowState.DISPUTED
    if frozen and resolution == DisputeResolution.DISMISSED:
        raise ValidationFailed(
            "The escrow is frozen on-chain, so the arbiter must route it: choose release to the contributor or "
            "refund to the requester."
        )
    now = utcnow()
    d.resolution = resolution
    d.resolution_note = note.strip()
    d.resolved_by_id = moderator.id
    d.resolved_at = now
    d.status = (
        DisputeStatus.DISMISSED if resolution == DisputeResolution.DISMISSED else DisputeStatus.RESOLVED
    )
    if d.assigned_moderator_id is None:
        d.assigned_moderator_id = moderator.id

    if not frozen:
        await _apply_offchain_resolution(session, bounty, d, moderator)
    # When frozen, the bounty stays DISPUTED until the arbiter's RESOLVE_DISPUTE transaction is verified.

    audit.record(
        session,
        actor_id=moderator.id,
        action="dispute.resolved",
        entity_type="dispute",
        entity_id=d.id,
        bounty_id=bounty.id,
        metadata={"resolution": resolution.value, "onchain_pending": frozen},
    )
    add_event(
        session,
        event_type=EventType.DISPUTE_RESOLVED,
        aggregate_type="bounty",
        aggregate_id=bounty.id,
        actor_id=moderator.id,
        payload={**_payload(d, bounty), "resolution": resolution.value},
    )
    await bounty_service.commit_bounty(session, bounty)
    return await get(session, moderator, d.id)


async def _apply_offchain_resolution(
    session: AsyncSession, bounty: Bounty, d: Dispute, moderator: User
) -> None:
    before = BountyStatus(d.status_before) if d.status_before else BountyStatus.IN_PROGRESS
    assignment = await session.scalar(
        select(BountyAssignment).where(
            BountyAssignment.bounty_id == bounty.id,
            BountyAssignment.contributor_id == d.contributor_id,
            BountyAssignment.status == AssignmentStatus.ACTIVE,
        )
    )
    submission = (
        await session.scalar(select(BountySubmission).where(BountySubmission.assignment_id == assignment.id))
        if assignment
        else None
    )
    now = utcnow()
    if d.resolution == DisputeResolution.RELEASE_TO_CONTRIBUTOR and submission is not None:
        if submission.status != SubmissionStatus.APPROVED:
            submission.status = SubmissionStatus.APPROVED
            submission.review_feedback = "Approved through dispute resolution."
            submission.reviewer_id = moderator.id
            submission.reviewed_at = now
        exists = await session.scalar(
            select(PaymentRecord.id).where(PaymentRecord.submission_id == submission.id)
        )
        if not exists:
            session.add(
                PaymentRecord(
                    id=uuid.uuid4(),
                    bounty_id=bounty.id,
                    contributor_id=submission.contributor_id,
                    submission_id=submission.id,
                    amount=bounty.reward_amount,
                    asset_identifier="native",
                    payment_status=PaymentStatus.CREATED,
                )
            )
    elif d.resolution == DisputeResolution.REFUND_TO_REQUESTER and assignment is not None:
        if not assignment.onchain_assigned:
            assignment.status = AssignmentStatus.RELEASED
            assignment.released_at = now
        if submission is not None and submission.status != SubmissionStatus.APPROVED:
            submission.status = SubmissionStatus.REJECTED
            submission.review_feedback = "Rejected through dispute resolution."
            submission.reviewer_id = moderator.id
            submission.reviewed_at = now
    if bounty.status != BountyStatus.DISPUTED:
        # The lifecycle already moved on while the dispute was open (e.g. a payout submitted before the dispute
        # confirmed and completed the bounty): record the decision, never force an illegal transition.
        return
    target = before if sm.can_transition(BountyStatus.DISPUTED, before) else BountyStatus.IN_PROGRESS
    bounty_service.change_status(session, bounty, target, actor_id=moderator.id, reason="dispute resolved")
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, moderator.id)
