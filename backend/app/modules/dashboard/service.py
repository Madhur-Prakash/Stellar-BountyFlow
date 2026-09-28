"""Role-aware dashboard aggregation for the authenticated user.

Recommendations are deterministic (no AI): open bounties the user does not own and has not applied to, ranked by
the number of required skills that match the user's profile skills, then by category interest, then recency.
"""

from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AuditLog
from app.modules.applications.models import (
    ApplicationStatus,
    AssignmentStatus,
    BountyApplication,
    BountyAssignment,
)
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties import state_machine as sm
from app.modules.bounties.models import Bounty, BountySkill, BountyStatus
from app.modules.dashboard.schemas import Dashboard
from app.modules.payments.models import PaymentRecord, PaymentStatus
from app.modules.submissions.models import BountySubmission, SubmissionStatus
from app.modules.users.models import User

ACTIVE = (
    BountyStatus.OPEN,
    BountyStatus.FUNDING_PENDING,
    BountyStatus.FUNDED,
    BountyStatus.IN_PROGRESS,
    BountyStatus.UNDER_REVIEW,
    BountyStatus.DISPUTED,
    BountyStatus.CANCEL_REQUESTED,
)


async def _count(session: AsyncSession, stmt: Select[int]) -> int:
    return int(await session.scalar(stmt) or 0)


async def recommendations(session: AsyncSession, user: User, limit: int = 6) -> list[Bounty]:
    applied = select(BountyApplication.bounty_id).where(BountyApplication.contributor_id == user.id)
    skills = user.skill_names
    match_count = (
        select(func.count(BountySkill.id))
        .where(BountySkill.bounty_id == Bounty.id, BountySkill.skill_name.in_(skills or ["__none__"]))
        .correlate(Bounty)
        .scalar_subquery()
    )
    stmt = (
        select(Bounty)
        .where(
            bounty_repo.public_filter(),
            Bounty.status.in_(sm.ACCEPTING_APPLICATIONS),
            Bounty.requester_id != user.id,
            Bounty.id.not_in(applied),
        )
        .order_by(
            match_count.desc(),
            func.coalesce(Bounty.published_at, Bounty.created_at).desc(),
        )
        .limit(limit)
    )
    return list((await session.scalars(stmt)).unique().all())


async def build(session: AsyncSession, user: User) -> Dashboard:
    mine = Bounty.requester_id == user.id
    active_bounties = await _count(
        session, select(func.count(Bounty.id)).where(mine, Bounty.status.in_(ACTIVE))
    )
    apps_to_review = await _count(
        session,
        select(func.count(BountyApplication.id))
        .join(Bounty, Bounty.id == BountyApplication.bounty_id)
        .where(mine, BountyApplication.status == ApplicationStatus.PENDING),
    )
    subs_to_review = await _count(
        session,
        select(func.count(BountySubmission.id))
        .join(Bounty, Bounty.id == BountySubmission.bounty_id)
        .where(mine, BountySubmission.status.in_([SubmissionStatus.SUBMITTED, SubmissionStatus.RESUBMITTED])),
    )
    pending_payments = await _count(
        session,
        select(func.count(PaymentRecord.id))
        .join(Bounty, Bounty.id == PaymentRecord.bounty_id)
        .where(
            mine,
            PaymentRecord.payment_status.in_(
                [
                    PaymentStatus.CREATED,
                    PaymentStatus.SIGNATURE_REQUIRED,
                    PaymentStatus.SUBMITTED,
                    PaymentStatus.FAILED,
                ]
            ),
        ),
    )
    my_pending_apps = await _count(
        session,
        select(func.count(BountyApplication.id)).where(
            BountyApplication.contributor_id == user.id, BountyApplication.status == ApplicationStatus.PENDING
        ),
    )
    my_assignments = await _count(
        session,
        select(func.count(BountyAssignment.id)).where(
            BountyAssignment.contributor_id == user.id, BountyAssignment.status == AssignmentStatus.ACTIVE
        ),
    )
    revisions = await _count(
        session,
        select(func.count(BountySubmission.id)).where(
            BountySubmission.contributor_id == user.id,
            BountySubmission.status == SubmissionStatus.REVISION_REQUESTED,
        ),
    )
    contributed = select(BountyAssignment.bounty_id).where(BountyAssignment.contributor_id == user.id)
    completed = (
        (
            await session.scalars(
                select(Bounty)
                .where(Bounty.status == BountyStatus.COMPLETED, or_(mine, Bounty.id.in_(contributed)))
                .order_by(Bounty.completed_at.desc().nulls_last())
                .limit(5)
            )
        )
        .unique()
        .all()
    )
    activity_rows = (
        (
            await session.scalars(
                select(AuditLog)
                .outerjoin(Bounty, Bounty.id == AuditLog.bounty_id)
                .where(
                    AuditLog.is_public.is_(True),
                    or_(
                        AuditLog.actor_id == user.id,
                        Bounty.requester_id == user.id,
                        Bounty.id.in_(contributed),
                    ),
                )
                .order_by(AuditLog.created_at.desc())
                .limit(12)
            )
        )
        .unique()
        .all()
    )
    bounty_ids = {r.bounty_id for r in activity_rows if r.bounty_id}
    bounties = {
        b.id: b for b in (await session.scalars(select(Bounty).where(Bounty.id.in_(bounty_ids)))).unique()
    }
    recs = await recommendations(session, user)
    return Dashboard(
        active_bounties=active_bounties,
        pending_applications_to_review=apps_to_review,
        submissions_awaiting_review=subs_to_review,
        pending_payments=pending_payments,
        my_pending_applications=my_pending_apps,
        my_active_assignments=my_assignments,
        revision_requests=revisions,
        recent_completed=await bounty_service.summaries(session, completed, user),
        recent_activity=[
            bounty_service.activity_item(r, bounties.get(r.bounty_id) if r.bounty_id else None)
            for r in activity_rows
        ],
        recommendations=await bounty_service.summaries(session, recs, user),
    )
