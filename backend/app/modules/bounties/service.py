"""Bounty use cases: authoring, publishing, discovery, lifecycle transitions, cancellation, and expiry."""

from __future__ import annotations

import re
import secrets
import unicodedata
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.blockchain.config import get_network
from app.cache import keys
from app.cache.invalidation import current_generation, invalidate_bounty, invalidate_profile
from app.cache.redis import cache_get_json, cache_set_json, get_redis
from app.core.exceptions import Conflict, Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.money import ZERO
from app.core.rbac import Permission, ensure_permission, has_permission
from app.core.schemas import Page, PageParams, UserSummary, asset_from_identifier
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.admin.models import AuditLog
from app.modules.applications.models import (
    ApplicationStatus,
    AssignmentStatus,
    BountyApplication,
    BountyAssignment,
)
from app.modules.assets import service as asset_registry
from app.modules.bounties import repository as repo
from app.modules.bounties import state_machine as sm
from app.modules.bounties.models import Bounty, BountyBookmark, BountyStatus
from app.modules.bounties.schemas import (
    ActivityBounty,
    ActivityItem,
    BountyCreate,
    BountyDetail,
    BountySummary,
    BountyUpdate,
    EscrowView,
    FundingStatus,
    Link,
    MarketplaceFilters,
    Viewer,
    ViewerApplication,
)
from app.modules.github.service import ensure_repository_supports_merge_requirement
from app.modules.payments.models import BountyEscrow, EscrowState, PaymentRecord, PaymentStatus
from app.modules.qa import repository as qa_repo
from app.modules.submissions.models import BountySubmission, SubmissionStatus
from app.modules.users.models import User

logger = get_logger(__name__)

PENDING_REVIEW = (SubmissionStatus.SUBMITTED, SubmissionStatus.RESUBMITTED)


# --- Serialization -------------------------------------------------------------------


def funding_status(bounty: Bounty, escrow: BountyEscrow | None) -> FundingStatus:
    pending = bounty.status == BountyStatus.FUNDING_PENDING
    if escrow is None or escrow.state == EscrowState.NOT_CREATED:
        return FundingStatus.PENDING if pending else FundingStatus.UNFUNDED
    if escrow.state == EscrowState.CANCELLED or (escrow.refunded_amount > ZERO):
        return FundingStatus.REFUNDED
    if escrow.state == EscrowState.COMPLETED:
        return FundingStatus.SETTLED
    if escrow.state == EscrowState.CANCEL_REQUESTED or bounty.status == BountyStatus.CANCEL_REQUESTED:
        return FundingStatus.REFUND_PENDING
    if escrow.funded_amount <= ZERO:
        return FundingStatus.PENDING if pending else FundingStatus.UNFUNDED
    if escrow.funded_amount < escrow.required_amount:
        return FundingStatus.PENDING if pending else FundingStatus.PARTIALLY_FUNDED
    return FundingStatus.FUNDED


def escrow_view(escrow: BountyEscrow | None) -> EscrowView | None:
    if escrow is None:
        return None
    network = get_network()
    return EscrowView(
        contract_id=escrow.contract_id,
        network=escrow.network,
        asset=asset_from_identifier(escrow.asset_identifier),
        onchain_bounty_id=escrow.onchain_bounty_id,
        required_amount=escrow.required_amount,
        funded_amount=escrow.funded_amount,
        paid_out_amount=escrow.paid_out_amount,
        refunded_amount=escrow.refunded_amount,
        state=escrow.state.value,
        last_reconciled_at=escrow.last_reconciled_at,
        explorer_url=network.contract_url(),
        contract_version=escrow.contract_version,
        arbiter_addresses=list(
            escrow.arbiter_addresses or ([escrow.arbiter_address] if escrow.arbiter_address else [])
        ),
        arbiter_threshold=escrow.arbiter_threshold,
        review_window_seconds=escrow.review_window_seconds,
    )


def user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id, username=user.username, display_name=user.display_name, avatar_url=user.avatar_url
    )


def _summary(bounty: Bounty, escrow: BountyEscrow | None, filled: int, bookmarked: bool) -> BountySummary:
    return BountySummary(
        id=bounty.id,
        slug=bounty.slug,
        title=bounty.title,
        short_description=bounty.short_description,
        category=bounty.category,
        difficulty=bounty.difficulty,
        tags=bounty.tag_names,
        required_skills=bounty.skill_names,
        reward_amount=bounty.reward_amount,
        reward_asset=asset_from_identifier(bounty.reward_asset_identifier),
        total_reward=bounty.total_reward,
        network=bounty.network,
        status=bounty.status,
        funding_status=funding_status(bounty, escrow),
        application_deadline=bounty.application_deadline,
        completion_deadline=bounty.completion_deadline,
        positions_available=bounty.positions_available,
        positions_filled=filled,
        applications_count=bounty.applications_count,
        requester=user_summary(bounty.requester),
        is_featured=bounty.is_featured,
        is_bookmarked=bookmarked,
        is_hidden=bounty.is_hidden,
        created_at=bounty.created_at,
        published_at=bounty.published_at,
    )


async def summaries(
    session: AsyncSession, bounties: Sequence[Bounty], viewer: User | None
) -> list[BountySummary]:
    ids = [b.id for b in bounties]
    filled = await repo.positions_filled(session, ids)
    escrows = await repo.escrows(session, ids)
    marks = await repo.bookmarked_ids(session, viewer.id, ids) if viewer else set()
    items = [_summary(b, escrows.get(b.id), filled.get(b.id, 0), b.id in marks) for b in bounties]
    questions = await qa_repo.question_counts(session, ids)
    for item in items:
        item.questions_count = questions.get(item.id, 0)
    return items


def _base_detail(bounty: Bounty, escrow: BountyEscrow | None, filled: int) -> BountyDetail:
    base = _summary(bounty, escrow, filled, False)
    meta = bounty.metadata_ or {}
    return BountyDetail(
        **base.model_dump(),
        description=bounty.description,
        eligibility_criteria=bounty.eligibility_criteria,
        submission_requirements=bounty.submission_requirements,
        acceptance_criteria=bounty.acceptance_criteria,
        repository_url=bounty.repository_url,
        require_merged_pr=bounty.require_merged_pr,
        links=[Link.model_validate(link) for link in meta.get("links", [])],
        visibility=bounty.visibility,
        escrow=escrow_view(escrow),
        cancel_reason=meta.get("cancel_reason"),
    )


async def viewer_state(
    session: AsyncSession, bounty: Bounty, viewer: User | None, filled: int
) -> Viewer | None:
    if viewer is None:
        return None
    is_owner = bounty.requester_id == viewer.id
    application = await session.scalar(
        select(BountyApplication)
        .where(BountyApplication.bounty_id == bounty.id, BountyApplication.contributor_id == viewer.id)
        .order_by(
            BountyApplication.status.in_([ApplicationStatus.PENDING, ApplicationStatus.ACCEPTED]).desc(),
            BountyApplication.created_at.desc(),
        )
        .limit(1)
    )
    assignment = await session.scalar(
        select(BountyAssignment).where(
            BountyAssignment.bounty_id == bounty.id,
            BountyAssignment.contributor_id == viewer.id,
            BountyAssignment.status.in_([AssignmentStatus.ACTIVE, AssignmentStatus.COMPLETED]),
        )
    )
    has_submission = False
    if assignment is not None:
        has_submission = bool(
            await session.scalar(
                select(func.count(BountySubmission.id)).where(BountySubmission.assignment_id == assignment.id)
            )
        )
    now = utcnow()
    live_application = application is not None and application.status in (
        ApplicationStatus.PENDING,
        ApplicationStatus.ACCEPTED,
    )
    can_apply = (
        not is_owner
        and viewer.is_active
        and not bounty.is_hidden
        and bounty.status in sm.ACCEPTING_APPLICATIONS
        and (bounty.application_deadline is None or bounty.application_deadline > now)
        and filled < bounty.positions_available
        and not live_application
    )
    can_submit = (
        assignment is not None
        and assignment.status == AssignmentStatus.ACTIVE
        and bounty.status in sm.WORK_ACTIVE
        and not has_submission
    )
    if (
        assignment is not None
        and assignment.status == AssignmentStatus.ACTIVE
        and bounty.status in sm.WORK_ACTIVE
    ):
        from app.modules.escrow import views as escrow_views

        # A milestone bounty takes one submission per milestone.
        milestone_open = await escrow_views.milestone_submit_open(session, bounty, assignment)
        if milestone_open is not None:
            can_submit = milestone_open
    return Viewer(
        is_owner=is_owner,
        is_assigned=assignment is not None and assignment.status == AssignmentStatus.ACTIVE,
        can_apply=can_apply,
        can_submit=can_submit,
        application=ViewerApplication(id=application.id, status=application.status) if application else None,
        assignment_id=assignment.id if assignment else None,
        is_moderator=has_permission(viewer, Permission.BOUNTY_MODERATE),
    )


async def detail(session: AsyncSession, bounty: Bounty, viewer: User | None) -> BountyDetail:
    filled = (await repo.positions_filled(session, [bounty.id])).get(bounty.id, 0)
    escrow = await repo.get_escrow(session, bounty.id)
    result = _base_detail(bounty, escrow, filled)
    result.questions_count = (await qa_repo.question_counts(session, [bounty.id])).get(bounty.id, 0)
    from app.modules.escrow import views as escrow_views  # escrow v2 depends on this module

    for key, value in (await escrow_views.bounty_extras(session, bounty)).items():
        setattr(result, key, value)
    if viewer is not None:
        result.is_bookmarked = bool(await repo.bookmarked_ids(session, viewer.id, [bounty.id]))
        result.viewer = await viewer_state(session, bounty, viewer, filled)
    return result


def _cacheable(bounty: Bounty) -> bool:
    return bounty.status != BountyStatus.DRAFT and not bounty.is_hidden


def can_view(bounty: Bounty, viewer: User | None) -> bool:
    if viewer is not None and (
        viewer.id == bounty.requester_id or has_permission(viewer, Permission.BOUNTY_VIEW_ALL)
    ):
        return True
    return bounty.status != BountyStatus.DRAFT and not bounty.is_hidden


# --- Transitions -----------------------------------------------------------------------


def change_status(
    session: AsyncSession,
    bounty: Bounty,
    target: BountyStatus,
    *,
    actor_id: uuid.UUID | None,
    reason: str | None = None,
    event_type: str | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Validates and applies a lifecycle transition, recording an audit entry and a domain event.

    ``extra`` is merged into the event payload (e.g. ``contributor_ids`` / ``applicant_ids`` so the notification
    worker can reach everyone affected, not just the requester)."""
    current = bounty.status
    if current == target:
        return False
    sm.assert_transition(current, target)
    bounty.status = target
    now = utcnow()
    if target == BountyStatus.COMPLETED:
        bounty.completed_at = now
    if target == BountyStatus.CANCELLED:
        bounty.cancelled_at = now
    audit.record(
        session,
        actor_id=actor_id,
        action=f"bounty.{target.value.lower()}",
        entity_type="bounty",
        entity_id=bounty.id,
        bounty_id=bounty.id,
        metadata={"from": current.value, "to": target.value, **({"reason": reason} if reason else {})},
    )
    add_event(
        session,
        event_type=event_type or EventType.BOUNTY_STATUS_CHANGED,
        aggregate_type="bounty",
        aggregate_id=bounty.id,
        actor_id=actor_id,
        payload={
            "bounty_id": bounty.id,
            "requester_id": bounty.requester_id,
            "title": bounty.title,
            "status": target.value,
            "previous_status": current.value,
            **(extra or {}),
        },
    )
    logger.info(
        "bounty_status_changed", bounty_id=str(bounty.id), from_status=current.value, to_status=target.value
    )
    return True


async def affected_parties(session: AsyncSession, bounty_id: uuid.UUID) -> dict[str, Any]:
    """Contributors with a live assignment and applicants still waiting, captured *before* a transition closes
    their work, so cancellation / expiry notifications can reach them."""
    contributors = (
        await session.scalars(
            select(BountyAssignment.contributor_id).where(
                BountyAssignment.bounty_id == bounty_id, BountyAssignment.status == AssignmentStatus.ACTIVE
            )
        )
    ).all()
    applicants = (
        await session.scalars(
            select(BountyApplication.contributor_id).where(
                BountyApplication.bounty_id == bounty_id,
                BountyApplication.status == ApplicationStatus.PENDING,
            )
        )
    ).all()
    return {"contributor_ids": list(contributors), "applicant_ids": list(applicants)}


async def recompute_operational_status(
    session: AsyncSession, bounty: Bounty, actor_id: uuid.UUID | None
) -> None:
    """For FUNDED/IN_PROGRESS/UNDER_REVIEW bounties, derive the aggregate status from live work."""
    if bounty.status not in sm.DERIVED:
        return
    active = await session.scalar(
        select(func.count(BountyAssignment.id)).where(
            BountyAssignment.bounty_id == bounty.id, BountyAssignment.status == AssignmentStatus.ACTIVE
        )
    )
    # Awaiting review, or approved but not yet settled on-chain (the assignment completes on verified payout).
    # Only live work counts: a submission whose assignment was completed (paid) or released (e.g. by a dispute
    # resolution or a cancellation) must never hold the bounty in UNDER_REVIEW.
    pending = await session.scalar(
        select(func.count(BountySubmission.id))
        .join(BountyAssignment, BountyAssignment.id == BountySubmission.assignment_id)
        .where(
            BountySubmission.bounty_id == bounty.id,
            BountyAssignment.status == AssignmentStatus.ACTIVE,
            BountySubmission.status.in_([*PENDING_REVIEW, SubmissionStatus.APPROVED]),
            # A paid milestone's submission stays APPROVED while the assignment continues (escrow v2).
            ~select(PaymentRecord.id)
            .where(
                PaymentRecord.submission_id == BountySubmission.id,
                PaymentRecord.payment_status == PaymentStatus.CONFIRMED,
            )
            .exists(),
        )
    )
    target = sm.derive_operational_status(active or 0, pending or 0)
    if target != bounty.status and sm.can_transition(bounty.status, target):
        change_status(session, bounty, target, actor_id=actor_id)


async def load_for_update(session: AsyncSession, bounty_id: uuid.UUID) -> Bounty:
    bounty = await repo.get(session, bounty_id, for_update=True)
    if bounty is None:
        raise NotFound("Bounty not found.")
    return bounty


async def commit_bounty(session: AsyncSession, bounty: Bounty) -> None:
    try:
        await session.commit()
    except StaleDataError as exc:
        await session.rollback()
        raise Conflict("This bounty was modified concurrently. Please retry.") from exc
    await invalidate_bounty(str(bounty.id), bounty.slug)


def _require_owner(bounty: Bounty, user: User) -> None:
    if bounty.requester_id != user.id:
        raise Forbidden("Only the bounty's requester can do this.")


# --- Authoring -------------------------------------------------------------------------


def slugify(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:150] or "bounty"


async def _unique_slug(session: AsyncSession, title: str) -> str:
    base = slugify(title)
    for _ in range(5):
        candidate = f"{base}-{secrets.token_hex(3)}"
        if not await repo.slug_exists(session, candidate):
            return candidate
    return f"{base}-{uuid.uuid4().hex[:12]}"


async def create_bounty(session: AsyncSession, user: User, data: BountyCreate) -> BountyDetail:
    ensure_permission(user, Permission.BOUNTY_CREATE)
    ensure_repository_supports_merge_requirement(data.repository_url, data.require_merged_pr)
    asset = await asset_registry.resolve_reward_asset(session, data.reward_asset)
    bounty = Bounty(
        id=uuid.uuid4(),
        requester_id=user.id,
        title=data.title,
        slug=await _unique_slug(session, data.title),
        short_description=data.short_description,
        description=data.description,
        category=data.category,
        difficulty=data.difficulty,
        reward_amount=Decimal(data.reward_amount),
        reward_asset=asset.code,
        reward_asset_identifier=asset.identifier,
        network=get_network().network,
        status=BountyStatus.DRAFT,
        application_deadline=data.application_deadline,
        completion_deadline=data.completion_deadline,
        positions_available=data.positions_available,
        eligibility_criteria=data.eligibility_criteria,
        submission_requirements=data.submission_requirements,
        acceptance_criteria=data.acceptance_criteria,
        repository_url=data.repository_url,
        require_merged_pr=data.require_merged_pr,
        visibility=data.visibility,
        metadata_={"links": [link.model_dump(mode="json") for link in data.links]},
        tags=[],
        skills=[],
    )
    repo.set_tags(bounty, data.tags)
    repo.set_skills(bounty, data.required_skills)
    session.add(bounty)
    if not user.wants_to_request:
        user.wants_to_request = True
    await session.flush()
    from app.modules.escrow import views as escrow_views

    await escrow_views.apply_create(session, bounty, data)  # review window and milestones (escrow v2)
    audit.record(
        session,
        actor_id=user.id,
        action="bounty.created",
        entity_type="bounty",
        entity_id=bounty.id,
        bounty_id=bounty.id,
        metadata={"title": bounty.title},
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.BOUNTY_CREATED,
        aggregate_type="bounty",
        aggregate_id=bounty.id,
        actor_id=user.id,
        payload={
            "bounty_id": bounty.id,
            "requester_id": user.id,
            "title": bounty.title,
            "status": bounty.status.value,
        },
    )
    await session.commit()
    await session.refresh(bounty)
    await invalidate_profile(user.username)
    return await detail(session, bounty, user)


async def update_bounty(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, data: BountyUpdate
) -> BountyDetail:
    bounty = await load_for_update(session, bounty_id)
    _require_owner(bounty, user)
    escrow = await repo.get_escrow(session, bounty.id)
    funded = escrow is not None and escrow.state != EscrowState.NOT_CREATED
    if bounty.status not in (BountyStatus.DRAFT, BountyStatus.OPEN) or funded:
        raise InvalidStateTransition("Bounties can only be edited while in draft or open and unfunded.")
    changes = data.model_dump(exclude_unset=True)
    money_fields = {"reward_amount", "reward_asset", "positions_available"} & changes.keys()
    if money_fields and bounty.status != BountyStatus.DRAFT:
        raise InvalidStateTransition("Reward and positions can only be changed while the bounty is a draft.")
    if changes.get("reward_asset") is not None:
        asset = await asset_registry.resolve_reward_asset(session, changes["reward_asset"])
        bounty.reward_asset = asset.code
        bounty.reward_asset_identifier = asset.identifier
    for field in (
        "title",
        "short_description",
        "description",
        "category",
        "difficulty",
        "eligibility_criteria",
        "submission_requirements",
        "acceptance_criteria",
        "repository_url",
        "require_merged_pr",
        "visibility",
        "application_deadline",
        "completion_deadline",
        "positions_available",
    ):
        if field in changes:
            value = changes[field]
            if value is None and field in (
                "title",
                "short_description",
                "description",
                "category",
                "difficulty",
                "visibility",
                "positions_available",
                "require_merged_pr",
            ):
                continue
            setattr(bounty, field, value)
    if "reward_amount" in changes and changes["reward_amount"] is not None:
        bounty.reward_amount = Decimal(changes["reward_amount"])
    if "tags" in changes and changes["tags"] is not None:
        repo.set_tags(bounty, changes["tags"])
    if "required_skills" in changes and changes["required_skills"] is not None:
        repo.set_skills(bounty, changes["required_skills"])
    if "links" in changes and changes["links"] is not None:
        bounty.metadata_ = {
            **(bounty.metadata_ or {}),
            "links": [Link.model_validate(link).model_dump(mode="json") for link in changes["links"]],
        }
    now = utcnow()
    for field in ("application_deadline", "completion_deadline"):
        value = changes.get(field)
        if value is not None and value <= now:  # publish enforces this too; an edit must not bypass it
            raise ValidationFailed(f"{field.replace('_', ' ').capitalize()} must be in the future.")
    _validate_deadlines(bounty)
    from app.modules.escrow import views as escrow_views

    await escrow_views.apply_update(session, bounty, data, set(changes))  # review window and milestones
    ensure_repository_supports_merge_requirement(bounty.repository_url, bounty.require_merged_pr)
    audit.record(
        session,
        actor_id=user.id,
        action="bounty.updated",
        entity_type="bounty",
        entity_id=bounty.id,
        bounty_id=bounty.id,
        metadata={"fields": sorted(changes.keys())},
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.BOUNTY_UPDATED,
        aggregate_type="bounty",
        aggregate_id=bounty.id,
        actor_id=user.id,
        payload={
            "bounty_id": bounty.id,
            "requester_id": user.id,
            "title": bounty.title,
            "status": bounty.status.value,
        },
    )
    await commit_bounty(session, bounty)
    await session.refresh(bounty)
    return await detail(session, bounty, user)


def _validate_deadlines(bounty: Bounty) -> None:
    a, c = bounty.application_deadline, bounty.completion_deadline
    if a and c and a > c:
        raise ValidationFailed("Application deadline must be before the completion deadline.")


async def publish(session: AsyncSession, user: User, bounty_id: uuid.UUID) -> BountyDetail:
    bounty = await load_for_update(session, bounty_id)
    _require_owner(bounty, user)
    if user.email_verified_at is None:
        raise Forbidden("Verify your email address before publishing a bounty.", code="email_not_verified")
    now = utcnow()
    for label, value in (
        ("Application deadline", bounty.application_deadline),
        ("Completion deadline", bounty.completion_deadline),
    ):
        if value is not None and value <= now:
            raise ValidationFailed(f"{label} has passed. Update it before publishing.")
    change_status(session, bounty, BountyStatus.OPEN, actor_id=user.id, event_type=EventType.BOUNTY_PUBLISHED)
    bounty.published_at = now
    await commit_bounty(session, bounty)
    await invalidate_profile(user.username)
    return await detail(session, bounty, user)


async def cancel(session: AsyncSession, user: User, bounty_id: uuid.UUID, reason: str) -> BountyDetail:
    bounty = await load_for_update(session, bounty_id)
    if bounty.requester_id != user.id and not has_permission(user, Permission.BOUNTY_MODERATE):
        raise Forbidden("Only the requester can cancel this bounty.")
    escrow = await repo.get_escrow(session, bounty.id)
    holds_funds = escrow is not None and escrow.funded_amount > ZERO and escrow.state != EscrowState.CANCELLED
    if bounty.status == BountyStatus.FUNDING_PENDING:
        raise InvalidStateTransition("A funding transaction is being confirmed. Try again once it settles.")
    bounty.metadata_ = {**(bounty.metadata_ or {}), "cancel_reason": reason}
    parties = await affected_parties(session, bounty.id)
    if not holds_funds and bounty.status in (BountyStatus.DRAFT, BountyStatus.OPEN, BountyStatus.EXPIRED):
        change_status(
            session,
            bounty,
            BountyStatus.CANCELLED,
            actor_id=user.id,
            reason=reason,
            event_type=EventType.BOUNTY_CANCELLED,
            extra=parties,
        )
        await _close_open_work(session, bounty)
    else:
        if not sm.can_transition(bounty.status, BountyStatus.CANCEL_REQUESTED):
            raise InvalidStateTransition(
                f"A {bounty.status.value.replace('_', ' ').lower()} bounty cannot be cancelled. "
                "Review pending submissions or resolve the dispute first."
            )
        change_status(
            session,
            bounty,
            BountyStatus.CANCEL_REQUESTED,
            actor_id=user.id,
            reason=reason,
            event_type=EventType.BOUNTY_CANCEL_REQUESTED,
            extra=parties,
        )
        await session.execute(
            update(BountyApplication)
            .where(
                BountyApplication.bounty_id == bounty.id,
                BountyApplication.status == ApplicationStatus.PENDING,
            )
            .values(status=ApplicationStatus.REJECTED, review_note="Bounty cancelled", reviewed_at=utcnow())
        )
    await commit_bounty(session, bounty)
    return await detail(session, bounty, user)


async def _close_open_work(session: AsyncSession, bounty: Bounty) -> None:
    now = utcnow()
    await session.execute(
        update(BountyApplication)
        .where(
            BountyApplication.bounty_id == bounty.id, BountyApplication.status == ApplicationStatus.PENDING
        )
        .values(status=ApplicationStatus.REJECTED, review_note="Bounty closed", reviewed_at=now)
    )
    await session.execute(
        update(BountyAssignment)
        .where(BountyAssignment.bounty_id == bounty.id, BountyAssignment.status == AssignmentStatus.ACTIVE)
        .values(status=AssignmentStatus.RELEASED, released_at=now)
    )


async def finalize_cancellation(session: AsyncSession, bounty: Bounty, actor_id: uuid.UUID | None) -> None:
    """Called once an on-chain refund is verified (or no funds were ever escrowed)."""
    if bounty.status == BountyStatus.CANCELLED:
        return
    if bounty.status == BountyStatus.EXPIRED or sm.can_transition(bounty.status, BountyStatus.CANCELLED):
        change_status(
            session,
            bounty,
            BountyStatus.CANCELLED,
            actor_id=actor_id,
            event_type=EventType.BOUNTY_CANCELLED,
            extra=await affected_parties(session, bounty.id),
        )
    await _close_open_work(session, bounty)


# --- Reads -------------------------------------------------------------------------------


async def get_bounty(
    session: AsyncSession, ref: str, viewer: User | None, *, viewer_key: str | None = None
) -> BountyDetail:
    bounty = await repo.get_by_id_or_slug(session, ref)
    if bounty is None or not can_view(bounty, viewer):
        raise NotFound("Bounty not found.")
    if viewer_key:
        await _count_view(session, bounty, viewer_key)
    if not _cacheable(bounty):
        return await detail(session, bounty, viewer)
    cache_key = keys.bounty_detail(str(bounty.id))
    cached = await cache_get_json(cache_key)
    if cached is None:
        base = await detail(session, bounty, None)
        await cache_set_json(cache_key, base.model_dump(mode="json"), keys.TTL_BOUNTY_DETAIL)
    else:
        base = BountyDetail.model_validate(cached)
    if viewer is not None:
        filled = base.positions_filled
        base.is_bookmarked = bool(await repo.bookmarked_ids(session, viewer.id, [bounty.id]))
        base.viewer = await viewer_state(session, bounty, viewer, filled)
    return base


async def _count_view(session: AsyncSession, bounty: Bounty, viewer_key: str) -> None:
    """Counts at most one view per viewer per bounty per day (popularity metric input)."""
    if bounty.status == BountyStatus.DRAFT:
        return
    try:
        first = await get_redis().set(keys.bounty_views(str(bounty.id), viewer_key), "1", nx=True, ex=86400)
    except Exception:
        return
    if first:
        await repo.record_view(session, bounty.id, datetime.now(UTC).date())
        await session.commit()


async def marketplace(
    session: AsyncSession, filters: MarketplaceFilters, params: PageParams, viewer: User | None
) -> Page[BountySummary]:
    generation = await current_generation()
    cache_key = keys.marketplace(
        generation, {**filters.cache_key_params(), "p": params.page, "s": params.page_size}
    )
    cached = await cache_get_json(cache_key) if generation >= 0 else None
    if cached is not None:
        page = Page[BountySummary].model_validate(cached)
    else:
        stmt, count_stmt = repo.marketplace_query(filters)
        total = int(await session.scalar(count_stmt) or 0)
        rows = (await session.scalars(stmt.offset(params.offset).limit(params.page_size))).unique().all()
        page = Page[BountySummary].build(await summaries(session, rows, None), total, params)
        if generation >= 0:
            await cache_set_json(cache_key, page.model_dump(mode="json"), keys.TTL_MARKETPLACE)
    if viewer is not None and page.items:
        marks = await repo.bookmarked_ids(session, viewer.id, [b.id for b in page.items])
        for item in page.items:
            item.is_bookmarked = item.id in marks
    return page


async def featured(session: AsyncSession, viewer: User | None) -> list[BountySummary]:
    generation = await current_generation()
    cache_key = keys.featured(generation)
    cached = await cache_get_json(cache_key) if generation >= 0 else None
    if cached is not None:
        items = [BountySummary.model_validate(i) for i in cached]
    else:
        rows = (
            (
                await session.scalars(
                    select(Bounty)
                    .where(repo.public_filter(), Bounty.status.in_(sm.MARKETPLACE_DEFAULT))
                    .order_by(
                        Bounty.is_featured.desc(),
                        Bounty.applications_count.desc(),
                        Bounty.published_at.desc().nulls_last(),
                    )
                    .limit(6)
                )
            )
            .unique()
            .all()
        )
        items = await summaries(session, rows, None)
        if generation >= 0:
            await cache_set_json(cache_key, [i.model_dump(mode="json") for i in items], keys.TTL_FEATURED)
    if viewer is not None and items:
        marks = await repo.bookmarked_ids(session, viewer.id, [b.id for b in items])
        for item in items:
            item.is_bookmarked = item.id in marks
    return items


async def my_bounties(
    session: AsyncSession, user: User, role: str, statuses: list[BountyStatus] | None, params: PageParams
) -> Page[BountySummary]:
    if role == "contributor":
        base = (
            select(Bounty)
            .join(BountyAssignment, BountyAssignment.bounty_id == Bounty.id)
            .where(
                BountyAssignment.contributor_id == user.id,
                BountyAssignment.status.in_([AssignmentStatus.ACTIVE, AssignmentStatus.COMPLETED]),
            )
        )
    else:
        base = select(Bounty).where(Bounty.requester_id == user.id)
    if statuses:
        base = base.where(Bounty.status.in_(statuses))
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(Bounty.updated_at.desc()).offset(params.offset).limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[BountySummary].build(await summaries(session, rows, user), total, params)


async def user_public_bounties(
    session: AsyncSession, user_id: uuid.UUID, params: PageParams, viewer: User | None
) -> Page[BountySummary]:
    base = select(Bounty).where(Bounty.requester_id == user_id, repo.public_filter())
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(Bounty.published_at.desc().nulls_last())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[BountySummary].build(await summaries(session, rows, viewer), total, params)


async def saved(session: AsyncSession, user: User, params: PageParams) -> Page[BountySummary]:
    base = (
        select(Bounty)
        .join(BountyBookmark, BountyBookmark.bounty_id == Bounty.id)
        .where(BountyBookmark.user_id == user.id, Bounty.is_hidden.is_(False))
    )
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(BountyBookmark.created_at.desc()).offset(params.offset).limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[BountySummary].build(await summaries(session, rows, user), total, params)


async def bookmark(session: AsyncSession, user: User, bounty_id: uuid.UUID) -> None:
    bounty = await repo.get(session, bounty_id)
    if bounty is None or not can_view(bounty, user):
        raise NotFound("Bounty not found.")
    if await repo.add_bookmark(session, user.id, bounty_id):
        await session.execute(
            update(Bounty)
            .where(Bounty.id == bounty_id)
            .values(bookmarks_count=Bounty.bookmarks_count + 1, version_id=Bounty.version_id + 1)
        )
    await session.commit()
    await invalidate_bounty(str(bounty_id))


async def unbookmark(session: AsyncSession, user: User, bounty_id: uuid.UUID) -> None:
    # DELETE ... RETURNING: only the request that actually removed the row decrements the counter (concurrent
    # unbookmarks used to decrement once each).
    deleted = await session.scalar(
        delete(BountyBookmark)
        .where(BountyBookmark.user_id == user.id, BountyBookmark.bounty_id == bounty_id)
        .returning(BountyBookmark.id)
    )
    if deleted is not None:
        await session.execute(
            update(Bounty)
            .where(Bounty.id == bounty_id)
            .values(
                bookmarks_count=func.greatest(Bounty.bookmarks_count - 1, 0), version_id=Bounty.version_id + 1
            )
        )
        await session.commit()
        await invalidate_bounty(str(bounty_id))


_ACTIVITY_LINKS = {
    "application": "/app/applications",
    "submission": "/app/submissions",
    "payment": "/app/payments",
    "transaction": "/app/transactions",
}


def activity_item(entry: AuditLog, bounty: Bounty | None) -> ActivityItem:
    link = f"/bounties/{bounty.slug}" if bounty else None
    return ActivityItem(
        id=entry.id,
        action=entry.action,
        actor=user_summary(entry.actor) if entry.actor else None,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        bounty=ActivityBounty(id=bounty.id, slug=bounty.slug, title=bounty.title) if bounty else None,
        metadata={k: v for k, v in (entry.metadata_ or {}).items() if k not in ("note", "review_note")},
        created_at=entry.created_at,
        link=link or _ACTIVITY_LINKS.get(entry.entity_type),
    )


async def activity(
    session: AsyncSession, ref: str, viewer: User | None, params: PageParams
) -> Page[ActivityItem]:
    bounty = await repo.get_by_id_or_slug(session, ref)
    if bounty is None or not can_view(bounty, viewer):
        raise NotFound("Bounty not found.")
    base = select(AuditLog).where(AuditLog.bounty_id == bounty.id, AuditLog.is_public.is_(True))
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(AuditLog.created_at.desc()).offset(params.offset).limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[ActivityItem].build([activity_item(r, bounty) for r in rows], total, params)


async def set_featured(
    session: AsyncSession, moderator: User, bounty_id: uuid.UUID, featured_flag: bool
) -> BountyDetail:
    ensure_permission(moderator, Permission.BOUNTY_FEATURE)
    bounty = await load_for_update(session, bounty_id)
    bounty.is_featured = featured_flag
    audit.record(
        session,
        actor_id=moderator.id,
        action="bounty.featured" if featured_flag else "bounty.unfeatured",
        entity_type="bounty",
        entity_id=bounty.id,
        bounty_id=bounty.id,
        is_public=False,
    )
    await commit_bounty(session, bounty)
    return await detail(session, bounty, moderator)


async def moderate(
    session: AsyncSession, moderator: User, bounty_id: uuid.UUID, action: str, reason: str
) -> BountyDetail:
    ensure_permission(moderator, Permission.BOUNTY_MODERATE)
    bounty = await load_for_update(session, bounty_id)
    if action == "HIDE":
        bounty.is_hidden = True
    elif action == "UNHIDE":
        bounty.is_hidden = False
    elif action == "CANCEL":
        await session.commit()
        return await cancel(session, moderator, bounty_id, f"Moderator: {reason}")
    audit.record(
        session,
        actor_id=moderator.id,
        action=f"bounty.moderated.{action.lower()}",
        entity_type="bounty",
        entity_id=bounty.id,
        bounty_id=bounty.id,
        metadata={"reason": reason},
        is_public=False,
    )
    await commit_bounty(session, bounty)
    return await detail(session, bounty, moderator)


# --- Lifecycle jobs (worker) ------------------------------------------------------------


async def expire_overdue(session: AsyncSession, limit: int = 100) -> int:
    """Expires open/funded bounties whose application deadline passed without any assigned contributor."""
    now = utcnow()
    deadline = func.coalesce(Bounty.application_deadline, Bounty.completion_deadline)
    # Eligibility is decided in SQL (not after LIMIT): otherwise `limit` overdue bounties that have a live or
    # completed assignment would be re-selected on every run and starve the eligible ones forever.
    has_live_assignment = (
        select(BountyAssignment.id)
        .where(
            BountyAssignment.bounty_id == Bounty.id,
            BountyAssignment.status.in_([AssignmentStatus.ACTIVE, AssignmentStatus.COMPLETED]),
        )
        .exists()
    )
    candidates = (
        (
            await session.scalars(
                select(Bounty)
                .where(
                    Bounty.status.in_([BountyStatus.OPEN, BountyStatus.FUNDED]),
                    deadline < now,
                    ~has_live_assignment,
                )
                .order_by(deadline)
                .with_for_update(of=Bounty, skip_locked=True)
                .limit(limit)
            )
        )
        .unique()
        .all()
    )
    expired = 0
    for bounty in candidates:
        change_status(
            session,
            bounty,
            BountyStatus.EXPIRED,
            actor_id=None,
            reason="deadline passed",
            event_type=EventType.BOUNTY_EXPIRED,
            extra=await affected_parties(session, bounty.id),
        )
        await session.execute(
            update(BountyApplication)
            .where(
                BountyApplication.bounty_id == bounty.id,
                BountyApplication.status == ApplicationStatus.PENDING,
            )
            .values(status=ApplicationStatus.REJECTED, review_note="Bounty expired", reviewed_at=now)
        )
        expired += 1
    await session.commit()
    for bounty in candidates:
        if bounty.status == BountyStatus.EXPIRED:
            await invalidate_bounty(str(bounty.id), bounty.slug)
    return expired


async def notify_deadlines(session: AsyncSession) -> int:
    """Emits one `deadline_approaching` event per bounty when the completion deadline is within 24h."""
    now = utcnow()
    rows = (
        (
            await session.scalars(
                select(Bounty)
                .where(
                    Bounty.status.in_([BountyStatus.IN_PROGRESS, BountyStatus.UNDER_REVIEW]),
                    Bounty.completion_deadline.is_not(None),
                    Bounty.completion_deadline > now,
                    Bounty.completion_deadline <= now + timedelta(hours=24),
                    Bounty.metadata_["deadline_notified"].astext.is_(None),
                )
                .with_for_update(of=Bounty, skip_locked=True)
                .limit(100)
            )
        )
        .unique()
        .all()
    )
    for bounty in rows:
        bounty.metadata_ = {**(bounty.metadata_ or {}), "deadline_notified": now.isoformat()}
        parties = await affected_parties(session, bounty.id)
        add_event(
            session,
            event_type=EventType.BOUNTY_DEADLINE_APPROACHING,
            aggregate_type="bounty",
            aggregate_id=bounty.id,
            payload={
                "bounty_id": bounty.id,
                "requester_id": bounty.requester_id,
                "title": bounty.title,
                "status": bounty.status.value,
                "deadline_type": "completion",
                "contributor_ids": parties["contributor_ids"],
            },
        )
    await session.commit()
    return len(rows)
