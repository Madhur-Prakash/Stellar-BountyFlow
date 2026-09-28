"""Submission lifecycle: submit, revise, review (request revision / approve / reject).

Approving a submission creates a `PaymentRecord` in state CREATED. The reward only moves once the requester
signs the on-chain `release` call and the backend independently verifies it (see payments.service).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.invalidation import invalidate_profile
from app.core.exceptions import Conflict, Forbidden, InvalidStateTransition, NotFound
from app.core.rbac import Permission, has_permission
from app.core.schemas import Page, PageParams
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.applications.schemas import ApplicationBounty
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties import state_machine as sm
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.payments.models import PaymentRecord, PaymentStatus
from app.modules.payments.schemas import serialize_payment
from app.modules.submissions.models import BountySubmission, SubmissionRevision, SubmissionStatus
from app.modules.submissions.schemas import (
    RevisionOut,
    SubmissionCreate,
    SubmissionOut,
    SubmissionUpdate,
)
from app.modules.users.models import User

REVIEWABLE = (SubmissionStatus.SUBMITTED, SubmissionStatus.RESUBMITTED)


def serialize(
    s: BountySubmission, payment: PaymentRecord | None = None, revisions: Sequence[SubmissionRevision] = ()
) -> SubmissionOut:
    return SubmissionOut(
        id=s.id,
        bounty_id=s.bounty_id,
        bounty=ApplicationBounty(
            id=s.bounty.id, slug=s.bounty.slug, title=s.bounty.title, status=s.bounty.status
        ),
        contributor=bounty_service.user_summary(s.contributor),
        assignment_id=s.assignment_id,
        version=s.version,
        description=s.description,
        evidence_url=s.evidence_url,
        evidence_links=list(s.evidence_links or []),
        status=s.status,
        review_feedback=s.review_feedback,
        reviewer=bounty_service.user_summary(s.reviewer) if s.reviewer else None,
        reviewed_at=s.reviewed_at,
        payment=serialize_payment(payment, s.bounty.title, s.bounty.slug) if payment else None,
        revisions=[RevisionOut.model_validate(r) for r in revisions],
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


async def _payments_for(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, PaymentRecord]:
    if not ids:
        return {}
    rows = await session.scalars(select(PaymentRecord).where(PaymentRecord.submission_id.in_(ids)))
    return {p.submission_id: p for p in rows.unique().all()}


def _payload(s: BountySubmission, bounty: Bounty) -> dict[str, object]:
    return {
        "submission_id": s.id,
        "bounty_id": bounty.id,
        "requester_id": bounty.requester_id,
        "contributor_id": s.contributor_id,
        "title": bounty.title,
        "status": s.status.value,
        "version": s.version,
    }


def _snapshot(s: BountySubmission) -> SubmissionRevision:
    return SubmissionRevision(
        submission_id=s.id,
        version=s.version,
        description=s.description,
        evidence_url=s.evidence_url,
        evidence_links=list(s.evidence_links or []),
    )


async def create(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, data: SubmissionCreate
) -> SubmissionOut:
    bounty = await bounty_service.load_for_update(session, bounty_id)
    assignment = await session.scalar(
        select(BountyAssignment).where(
            BountyAssignment.bounty_id == bounty.id,
            BountyAssignment.contributor_id == user.id,
            BountyAssignment.status == AssignmentStatus.ACTIVE,
        )
    )
    if assignment is None:
        raise Forbidden("Only contributors assigned to this bounty can submit work.")
    if bounty.status not in sm.WORK_ACTIVE:
        raise InvalidStateTransition(f"Submissions are closed while the bounty is {bounty.status.value}.")
    existing = await session.scalar(
        select(BountySubmission.id).where(BountySubmission.assignment_id == assignment.id)
    )
    if existing:
        raise Conflict("You have already submitted work. Update it when a revision is requested.")
    submission = BountySubmission(
        id=uuid.uuid4(),
        bounty_id=bounty.id,
        contributor_id=user.id,
        assignment_id=assignment.id,
        version=1,
        description=data.description,
        evidence_url=data.evidence_url,
        evidence_links=[str(u) for u in data.evidence_links],
        status=SubmissionStatus.SUBMITTED,
    )
    session.add(submission)
    await session.flush()
    session.add(_snapshot(submission))
    audit.record(
        session,
        actor_id=user.id,
        action="submission.created",
        entity_type="submission",
        entity_id=submission.id,
        bounty_id=bounty.id,
        metadata={"version": 1},
    )
    add_event(
        session,
        event_type=EventType.SUBMISSION_CREATED,
        aggregate_type="submission",
        aggregate_id=submission.id,
        actor_id=user.id,
        payload=_payload(submission, bounty),
    )
    await bounty_service.recompute_operational_status(session, bounty, user.id)
    await bounty_service.commit_bounty(session, bounty)
    await session.refresh(submission)
    return serialize(submission)


async def _lock_with_bounty(
    session: AsyncSession, submission_id: uuid.UUID
) -> tuple[BountySubmission, Bounty]:
    """Lock order: bounty row first, then the submission (the same order every service uses)."""
    bounty_id = await session.scalar(
        select(BountySubmission.bounty_id).where(BountySubmission.id == submission_id)
    )
    if bounty_id is None:
        raise NotFound("Submission not found.")
    bounty = await bounty_service.load_for_update(session, bounty_id)
    s = await _load(session, submission_id, for_update=True)
    return s, bounty


async def _load(
    session: AsyncSession, submission_id: uuid.UUID, *, for_update: bool = False
) -> BountySubmission:
    stmt = select(BountySubmission).where(BountySubmission.id == submission_id)
    if for_update:
        stmt = stmt.with_for_update(of=BountySubmission).execution_options(populate_existing=True)
    submission = await session.scalar(stmt)
    if submission is None:
        raise NotFound("Submission not found.")
    return submission


def _can_read(s: BountySubmission, user: User) -> bool:
    return (
        s.contributor_id == user.id
        or s.bounty.requester_id == user.id
        or has_permission(user, Permission.SUBMISSION_VIEW_ALL)
    )


async def get(session: AsyncSession, user: User, submission_id: uuid.UUID) -> SubmissionOut:
    s = await _load(session, submission_id)
    if not _can_read(s, user):
        raise NotFound("Submission not found.")
    payment = (await _payments_for(session, [s.id])).get(s.id)
    revisions = (
        await session.scalars(
            select(SubmissionRevision)
            .where(SubmissionRevision.submission_id == s.id)
            .order_by(SubmissionRevision.version)
        )
    ).all()
    return serialize(s, payment, revisions)


async def list_for_bounty(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, params: PageParams
) -> Page[SubmissionOut]:
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None:
        raise NotFound("Bounty not found.")
    base = select(BountySubmission).where(BountySubmission.bounty_id == bounty_id)
    if bounty.requester_id != user.id and not has_permission(user, Permission.SUBMISSION_VIEW_ALL):
        base = base.where(BountySubmission.contributor_id == user.id)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(BountySubmission.updated_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    payments = await _payments_for(session, [r.id for r in rows])
    return Page[SubmissionOut].build([serialize(r, payments.get(r.id)) for r in rows], total, params)


async def mine(
    session: AsyncSession, user: User, status: SubmissionStatus | None, params: PageParams
) -> Page[SubmissionOut]:
    base = select(BountySubmission).where(BountySubmission.contributor_id == user.id)
    if status:
        base = base.where(BountySubmission.status == status)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(BountySubmission.updated_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    payments = await _payments_for(session, [r.id for r in rows])
    return Page[SubmissionOut].build([serialize(r, payments.get(r.id)) for r in rows], total, params)


async def resubmit(
    session: AsyncSession, user: User, submission_id: uuid.UUID, data: SubmissionUpdate
) -> SubmissionOut:
    s, bounty = await _lock_with_bounty(session, submission_id)
    if s.contributor_id != user.id:
        raise NotFound("Submission not found.")
    if s.status != SubmissionStatus.REVISION_REQUESTED:
        raise InvalidStateTransition("You can only update a submission after a revision has been requested.")
    if bounty.status not in sm.WORK_ACTIVE:
        raise InvalidStateTransition(f"Submissions are closed while the bounty is {bounty.status.value}.")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("description"):
        s.description = changes["description"].strip()
    if "evidence_url" in changes:
        s.evidence_url = str(changes["evidence_url"]) if changes["evidence_url"] else None
    if changes.get("evidence_links") is not None:
        s.evidence_links = [str(u) for u in changes["evidence_links"]]
    s.version += 1
    s.status = SubmissionStatus.RESUBMITTED
    session.add(_snapshot(s))
    audit.record(
        session,
        actor_id=user.id,
        action="submission.resubmitted",
        entity_type="submission",
        entity_id=s.id,
        bounty_id=bounty.id,
        metadata={"version": s.version},
    )
    add_event(
        session,
        event_type=EventType.SUBMISSION_RESUBMITTED,
        aggregate_type="submission",
        aggregate_id=s.id,
        actor_id=user.id,
        payload=_payload(s, bounty),
    )
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, user.id)
    await bounty_service.commit_bounty(session, bounty)
    return await get(session, user, s.id)


async def _load_for_review(
    session: AsyncSession, user: User, submission_id: uuid.UUID
) -> tuple[BountySubmission, Bounty]:
    s, bounty = await _lock_with_bounty(session, submission_id)
    if bounty.requester_id != user.id:
        raise Forbidden("Only the requester can review submissions.")
    if bounty.status == BountyStatus.DISPUTED:
        raise InvalidStateTransition("Reviews are frozen while a dispute is open.")
    if s.status not in REVIEWABLE:
        raise InvalidStateTransition(f"A {s.status.value.lower()} submission cannot be reviewed.")
    return s, bounty


def _mark_reviewed(s: BountySubmission, user: User, status: SubmissionStatus, feedback: str | None) -> None:
    s.status = status
    s.review_feedback = feedback
    s.reviewer_id = user.id
    s.reviewed_at = utcnow()


async def request_revision(
    session: AsyncSession, user: User, submission_id: uuid.UUID, feedback: str
) -> SubmissionOut:
    s, bounty = await _load_for_review(session, user, submission_id)
    _mark_reviewed(s, user, SubmissionStatus.REVISION_REQUESTED, feedback)
    audit.record(
        session,
        actor_id=user.id,
        action="submission.revision_requested",
        entity_type="submission",
        entity_id=s.id,
        bounty_id=bounty.id,
        metadata={"version": s.version},
    )
    add_event(
        session,
        event_type=EventType.SUBMISSION_REVISION_REQUESTED,
        aggregate_type="submission",
        aggregate_id=s.id,
        actor_id=user.id,
        payload=_payload(s, bounty),
    )
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, user.id)
    await bounty_service.commit_bounty(session, bounty)
    return await get(session, user, s.id)


async def approve(
    session: AsyncSession, user: User, submission_id: uuid.UUID, feedback: str | None
) -> SubmissionOut:
    s, bounty = await _load_for_review(session, user, submission_id)
    _mark_reviewed(s, user, SubmissionStatus.APPROVED, feedback)
    existing = await session.scalar(select(PaymentRecord).where(PaymentRecord.submission_id == s.id))
    if existing is None:
        session.add(
            PaymentRecord(
                id=uuid.uuid4(),
                bounty_id=bounty.id,
                contributor_id=s.contributor_id,
                submission_id=s.id,
                amount=bounty.reward_amount,
                asset_identifier="native",
                payment_status=PaymentStatus.CREATED,
            )
        )
    audit.record(
        session,
        actor_id=user.id,
        action="submission.approved",
        entity_type="submission",
        entity_id=s.id,
        bounty_id=bounty.id,
        metadata={"version": s.version},
    )
    add_event(
        session,
        event_type=EventType.SUBMISSION_APPROVED,
        aggregate_type="submission",
        aggregate_id=s.id,
        actor_id=user.id,
        payload=_payload(s, bounty),
    )
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, user.id)
    await bounty_service.commit_bounty(session, bounty)
    await invalidate_profile(s.contributor.username)  # approval_rate changed
    return await get(session, user, s.id)


async def reject(session: AsyncSession, user: User, submission_id: uuid.UUID, reason: str) -> SubmissionOut:
    s, bounty = await _load_for_review(session, user, submission_id)
    _mark_reviewed(s, user, SubmissionStatus.REJECTED, reason)
    assignment = await session.get(BountyAssignment, s.assignment_id, with_for_update=True)
    if assignment is not None and assignment.status == AssignmentStatus.ACTIVE:
        assignment.status = AssignmentStatus.RELEASED
        assignment.released_at = utcnow()
    audit.record(
        session,
        actor_id=user.id,
        action="submission.rejected",
        entity_type="submission",
        entity_id=s.id,
        bounty_id=bounty.id,
        metadata={"version": s.version},
    )
    add_event(
        session,
        event_type=EventType.SUBMISSION_REJECTED,
        aggregate_type="submission",
        aggregate_id=s.id,
        actor_id=user.id,
        payload=_payload(s, bounty),
    )
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, user.id)
    await bounty_service.commit_bounty(session, bounty)
    await invalidate_profile(s.contributor.username)
    return await get(session, user, s.id)
