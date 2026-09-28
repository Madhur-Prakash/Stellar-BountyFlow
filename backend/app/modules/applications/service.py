"""Application lifecycle: apply, withdraw, accept (contributor selection), reject.

Contributor selection locks the bounty row (SELECT ... FOR UPDATE) so concurrent accepts can never exceed the
number of open positions; the database additionally enforces one live application/assignment per contributor.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.config import get_network
from app.cache.invalidation import invalidate_bounty, invalidate_profile
from app.core.exceptions import Conflict, Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.rbac import Permission, ensure_permission, has_permission
from app.core.schemas import Page, PageParams
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.applications.models import (
    ApplicationStatus,
    AssignmentStatus,
    BountyApplication,
    BountyAssignment,
)
from app.modules.applications.schemas import (
    ApplicationBounty,
    ApplicationCreate,
    ApplicationOut,
    ContributorSummary,
)
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties import state_machine as sm
from app.modules.bounties.models import Bounty
from app.modules.submissions.models import BountySubmission
from app.modules.users import repository as users_repo
from app.modules.users.models import User


def serialize(
    app: BountyApplication,
    *,
    show_note: bool,
    assignment_id: uuid.UUID | None = None,
    onchain_assigned: bool = False,
) -> ApplicationOut:
    c = app.contributor
    return ApplicationOut(
        id=app.id,
        bounty_id=app.bounty_id,
        bounty=ApplicationBounty(
            id=app.bounty.id, slug=app.bounty.slug, title=app.bounty.title, status=app.bounty.status
        ),
        contributor=ContributorSummary(
            id=c.id,
            username=c.username,
            display_name=c.display_name,
            avatar_url=c.avatar_url,
            skills=c.skill_names,
        ),
        cover_message=app.cover_message,
        relevant_experience=app.relevant_experience,
        work_samples=list(app.work_samples or []),
        status=app.status,
        review_note=app.review_note if show_note else None,
        assignment_id=assignment_id,
        onchain_assigned=onchain_assigned,
        reviewed_at=app.reviewed_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


async def _assignments(
    session: AsyncSession, app_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[uuid.UUID, bool]]:
    """application id -> (assignment id, assigned on-chain)."""
    if not app_ids:
        return {}
    rows = await session.execute(
        select(BountyAssignment.application_id, BountyAssignment.id, BountyAssignment.onchain_assigned).where(
            BountyAssignment.application_id.in_(app_ids)
        )
    )
    return {app_id: (assignment_id, onchain) for app_id, assignment_id, onchain in rows.all()}


def _serialize_many(
    rows: Sequence[BountyApplication],
    assignments: dict[uuid.UUID, tuple[uuid.UUID, bool]],
    *,
    show_note: bool,
) -> list[ApplicationOut]:
    out = []
    for r in rows:
        assignment_id, onchain = assignments.get(r.id, (None, False))
        out.append(serialize(r, show_note=show_note, assignment_id=assignment_id, onchain_assigned=onchain))
    return out


def _payload(app: BountyApplication, bounty: Bounty) -> dict[str, object]:
    return {
        "application_id": app.id,
        "bounty_id": bounty.id,
        "requester_id": bounty.requester_id,
        "contributor_id": app.contributor_id,
        "title": bounty.title,
        "status": app.status.value,
    }


async def _live_positions(session: AsyncSession, bounty_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count(BountyAssignment.id)).where(
                BountyAssignment.bounty_id == bounty_id,
                BountyAssignment.status.in_([AssignmentStatus.ACTIVE, AssignmentStatus.COMPLETED]),
            )
        )
        or 0
    )


async def apply(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, data: ApplicationCreate
) -> ApplicationOut:
    ensure_permission(user, Permission.APPLICATION_CREATE)
    bounty = await bounty_service.load_for_update(session, bounty_id)
    if bounty.requester_id == user.id:
        raise Forbidden("You cannot apply to your own bounty.")
    if bounty.is_hidden or bounty.status not in sm.ACCEPTING_APPLICATIONS:
        raise InvalidStateTransition("This bounty is not accepting applications.")
    if bounty.application_deadline and bounty.application_deadline <= utcnow():
        raise InvalidStateTransition("The application deadline has passed.")
    if await _live_positions(session, bounty.id) >= bounty.positions_available:
        raise InvalidStateTransition("All positions for this bounty are filled.")
    existing = await session.scalar(
        select(BountyApplication.id).where(
            BountyApplication.bounty_id == bounty.id,
            BountyApplication.contributor_id == user.id,
            BountyApplication.status.in_([ApplicationStatus.PENDING, ApplicationStatus.ACCEPTED]),
        )
    )
    if existing:
        raise Conflict("You already have an active application for this bounty.")
    app = BountyApplication(
        id=uuid.uuid4(),
        bounty_id=bounty.id,
        contributor_id=user.id,
        cover_message=data.cover_message,
        relevant_experience=data.relevant_experience,
        work_samples=[str(u) for u in data.work_samples],
        status=ApplicationStatus.PENDING,
    )
    session.add(app)
    bounty.applications_count += 1
    if not user.wants_to_contribute:
        user.wants_to_contribute = True
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("You already have an active application for this bounty.") from exc
    audit.record(
        session,
        actor_id=user.id,
        action="application.created",
        entity_type="application",
        entity_id=app.id,
        bounty_id=bounty.id,
    )
    add_event(
        session,
        event_type=EventType.APPLICATION_CREATED,
        aggregate_type="application",
        aggregate_id=app.id,
        actor_id=user.id,
        payload=_payload(app, bounty),
    )
    await bounty_service.commit_bounty(session, bounty)
    await invalidate_profile(user.username)  # applications_submitted changed
    await session.refresh(app)
    return serialize(app, show_note=False)


async def list_for_bounty(
    session: AsyncSession,
    user: User,
    bounty_id: uuid.UUID,
    status: ApplicationStatus | None,
    params: PageParams,
) -> Page[ApplicationOut]:
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None:
        raise NotFound("Bounty not found.")
    if bounty.requester_id != user.id and not has_permission(user, Permission.APPLICATION_VIEW_ALL):
        raise Forbidden("Only the requester can review applications.")
    base = select(BountyApplication).where(BountyApplication.bounty_id == bounty_id)
    if status:
        base = base.where(BountyApplication.status == status)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(BountyApplication.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    assignments = await _assignments(session, [r.id for r in rows])
    return Page[ApplicationOut].build(_serialize_many(rows, assignments, show_note=True), total, params)


async def my_applications(
    session: AsyncSession, user: User, status: ApplicationStatus | None, params: PageParams
) -> Page[ApplicationOut]:
    base = select(BountyApplication).where(BountyApplication.contributor_id == user.id)
    if status:
        base = base.where(BountyApplication.status == status)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(BountyApplication.updated_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    assignments = await _assignments(session, [r.id for r in rows])
    return Page[ApplicationOut].build(_serialize_many(rows, assignments, show_note=False), total, params)


async def _lock_application_and_bounty(
    session: AsyncSession, application_id: uuid.UUID
) -> tuple[BountyApplication, Bounty]:
    """Locks in a fixed order — bounty row first, then the application — so concurrent reviews of different
    applications on the same bounty serialise on the bounty instead of deadlocking."""
    bounty_id = await session.scalar(
        select(BountyApplication.bounty_id).where(BountyApplication.id == application_id)
    )
    if bounty_id is None:
        raise NotFound("Application not found.")
    bounty = await bounty_service.load_for_update(session, bounty_id)
    app = await session.scalar(
        select(BountyApplication)
        .where(BountyApplication.id == application_id)
        .with_for_update(of=BountyApplication)
        .execution_options(populate_existing=True)
    )
    if app is None:
        raise NotFound("Application not found.")
    return app, bounty


async def withdraw(session: AsyncSession, user: User, application_id: uuid.UUID) -> ApplicationOut:
    app, bounty = await _lock_application_and_bounty(session, application_id)
    if app.contributor_id != user.id:
        raise NotFound("Application not found.")
    if app.status == ApplicationStatus.PENDING:
        pass
    elif app.status == ApplicationStatus.ACCEPTED:
        assignment = await session.scalar(
            select(BountyAssignment).where(BountyAssignment.application_id == app.id).with_for_update()
        )
        if assignment is None or assignment.status != AssignmentStatus.ACTIVE:
            raise InvalidStateTransition("This application can no longer be withdrawn.")
        if assignment.onchain_assigned:
            raise InvalidStateTransition(
                "Your assignment is locked on-chain. Ask the requester to cancel, then consent to the cancellation."
            )
        submitted = await session.scalar(
            select(func.count(BountySubmission.id)).where(BountySubmission.assignment_id == assignment.id)
        )
        if submitted:
            raise InvalidStateTransition("You cannot withdraw after submitting work.")
        assignment.status = AssignmentStatus.RELEASED
        assignment.released_at = utcnow()
    else:
        raise InvalidStateTransition(f"A {app.status.value.lower()} application cannot be withdrawn.")
    app.status = ApplicationStatus.WITHDRAWN
    audit.record(
        session,
        actor_id=user.id,
        action="application.withdrawn",
        entity_type="application",
        entity_id=app.id,
        bounty_id=bounty.id,
    )
    add_event(
        session,
        event_type=EventType.APPLICATION_WITHDRAWN,
        aggregate_type="application",
        aggregate_id=app.id,
        actor_id=user.id,
        payload=_payload(app, bounty),
    )
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, user.id)
    await bounty_service.commit_bounty(session, bounty)
    await invalidate_profile(user.username)
    await session.refresh(app)
    return serialize(app, show_note=False)


async def accept(
    session: AsyncSession, user: User, application_id: uuid.UUID, note: str | None
) -> ApplicationOut:
    app, bounty = await _lock_application_and_bounty(session, application_id)  # serialises selections
    if bounty.requester_id != user.id:
        raise Forbidden("Only the requester can accept applicants.")
    if app.status != ApplicationStatus.PENDING:
        raise InvalidStateTransition(f"A {app.status.value.lower()} application cannot be accepted.")
    if bounty.status not in sm.CAN_ASSIGN:
        raise InvalidStateTransition(
            "Fund the bounty escrow before selecting contributors — contributors only start on funded work."
        )
    filled = await _live_positions(session, bounty.id)
    if filled >= bounty.positions_available:
        raise Conflict("All positions for this bounty are already filled.")
    network = get_network()
    if not await users_repo.has_verified_wallet(session, app.contributor_id, network.network):
        raise ValidationFailed(
            "This contributor has not connected a verified wallet yet, so they could not receive the reward. "
            "Ask them to connect a wallet first.",
            code="contributor_wallet_missing",
        )
    now = utcnow()
    app.status = ApplicationStatus.ACCEPTED
    app.reviewed_at = now
    app.reviewed_by_id = user.id
    app.review_note = note
    assignment = BountyAssignment(
        id=uuid.uuid4(),
        bounty_id=bounty.id,
        contributor_id=app.contributor_id,
        application_id=app.id,
        status=AssignmentStatus.ACTIVE,
        assigned_at=now,
    )
    session.add(assignment)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("This contributor is already assigned to the bounty.") from exc
    audit.record(
        session,
        actor_id=user.id,
        action="application.accepted",
        entity_type="application",
        entity_id=app.id,
        bounty_id=bounty.id,
        metadata={"contributor": app.contributor.username},
    )
    add_event(
        session,
        event_type=EventType.APPLICATION_ACCEPTED,
        aggregate_type="application",
        aggregate_id=app.id,
        actor_id=user.id,
        payload=_payload(app, bounty),
    )
    if filled + 1 >= bounty.positions_available:
        # All positions are taken: close remaining applications so applicants are not left waiting.
        await session.execute(
            update(BountyApplication)
            .where(
                BountyApplication.bounty_id == bounty.id,
                BountyApplication.status == ApplicationStatus.PENDING,
                BountyApplication.id != app.id,
            )
            .values(
                status=ApplicationStatus.REJECTED, review_note="All positions were filled.", reviewed_at=now
            )
        )
    await bounty_service.recompute_operational_status(session, bounty, user.id)
    await bounty_service.commit_bounty(session, bounty)
    await invalidate_profile(app.contributor.username)
    await session.refresh(app)
    return serialize(app, show_note=True, assignment_id=assignment.id)


async def reject(
    session: AsyncSession, user: User, application_id: uuid.UUID, note: str | None
) -> ApplicationOut:
    app, bounty = await _lock_application_and_bounty(session, application_id)
    if bounty.requester_id != user.id:
        raise Forbidden("Only the requester can reject applicants.")
    if app.status != ApplicationStatus.PENDING:
        raise InvalidStateTransition(f"A {app.status.value.lower()} application cannot be rejected.")
    app.status = ApplicationStatus.REJECTED
    app.reviewed_at = utcnow()
    app.reviewed_by_id = user.id
    app.review_note = note
    audit.record(
        session,
        actor_id=user.id,
        action="application.rejected",
        entity_type="application",
        entity_id=app.id,
        bounty_id=bounty.id,
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.APPLICATION_REJECTED,
        aggregate_type="application",
        aggregate_id=app.id,
        actor_id=user.id,
        payload=_payload(app, bounty),
    )
    await session.commit()
    await invalidate_bounty(str(bounty.id), bounty.slug)
    await invalidate_profile(app.contributor.username)  # acceptance_rate changed
    await session.refresh(app)
    return serialize(app, show_note=True)
