"""Bounty endpoints: marketplace discovery, authoring, lifecycle, bookmarks, reports, and activity."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.exceptions import NotFound, ValidationFailed
from app.core.rate_limit import client_ip, rate_limit
from app.core.rbac import Permission
from app.core.schemas import APIModel, Page, PageParams
from app.dependencies import CurrentUser, OptionalUser, SessionDep, require_permission
from app.modules.admin.models import ReportTarget
from app.modules.bounties import service
from app.modules.bounties.models import BountyStatus, Category, Difficulty
from app.modules.bounties.schemas import (
    ActivityItem,
    BountyCreate,
    BountyDetail,
    BountySummary,
    BountyUpdate,
    CancelRequest,
    FeatureRequest,
    MarketplaceFilters,
    ReportRequest,
    SortOption,
)
from app.modules.users.models import User

router = APIRouter(prefix="/bounties", tags=["bounties"])


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationFailed(
            "Invalid number.", details=[{"field": field, "message": "Must be a number"}]
        ) from exc
    if result < 0 or not result.is_finite():
        raise ValidationFailed("Invalid number.", details=[{"field": field, "message": "Must be >= 0"}])
    return result


def marketplace_filters(
    q: Annotated[str | None, Query(max_length=200)] = None,
    category: str | None = None,
    skills: str | None = None,
    tags: str | None = None,
    difficulty: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    min_reward: str | None = None,
    max_reward: str | None = None,
    deadline_before: datetime | None = None,
    deadline_after: datetime | None = None,
    funded_only: bool = False,
    sort: SortOption | None = None,
) -> MarketplaceFilters:
    try:
        return MarketplaceFilters(
            q=q,
            category=[Category(c.upper()) for c in _csv(category) or []] or None,
            skills=[s.lower() for s in _csv(skills) or []] or None,
            tags=[t.lower() for t in _csv(tags) or []] or None,
            difficulty=[Difficulty(d.upper()) for d in _csv(difficulty) or []] or None,
            status=[BountyStatus(s.upper()) for s in _csv(status_) or []] or None,
            min_reward=_decimal(min_reward, "min_reward"),
            max_reward=_decimal(max_reward, "max_reward"),
            deadline_before=deadline_before,
            deadline_after=deadline_after,
            funded_only=funded_only,
            sort=sort,
        )
    except ValueError as exc:
        raise ValidationFailed(
            "Invalid filter value.", details=[{"field": "filters", "message": str(exc)}]
        ) from exc


@router.get("", response_model=Page[BountySummary])
async def list_bounties(
    session: SessionDep,
    viewer: OptionalUser,
    filters: Annotated[MarketplaceFilters, Depends(marketplace_filters)],
    params: Annotated[PageParams, Depends()],
) -> Page[BountySummary]:
    return await service.marketplace(session, filters, params, viewer)


@router.get("/featured", response_model=list[BountySummary])
async def featured(session: SessionDep, viewer: OptionalUser) -> list[BountySummary]:
    return await service.featured(session, viewer)


@router.get("/mine", response_model=Page[BountySummary])
async def mine(
    session: SessionDep,
    user: CurrentUser,
    params: Annotated[PageParams, Depends()],
    role: Literal["requester", "contributor"] = "requester",
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> Page[BountySummary]:
    try:
        statuses = [BountyStatus(s.upper()) for s in _csv(status_) or []] or None
    except ValueError as exc:  # an unknown status is a client error (422), not a 500
        raise ValidationFailed(
            "Invalid filter value.", details=[{"field": "status", "message": str(exc)}]
        ) from exc
    return await service.my_bounties(session, user, role, statuses, params)


@router.get("/saved", response_model=Page[BountySummary])
async def saved(
    session: SessionDep, user: CurrentUser, params: Annotated[PageParams, Depends()]
) -> Page[BountySummary]:
    return await service.saved(session, user, params)


@router.post(
    "",
    response_model=BountyDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("bounty:create", 30, 3600))],
)
async def create(
    data: BountyCreate,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.BOUNTY_CREATE))],
) -> BountyDetail:
    return await service.create_bounty(session, user, data)


@router.get("/{bounty_ref}", response_model=BountyDetail)
async def get_bounty(
    bounty_ref: str, request: Request, session: SessionDep, viewer: OptionalUser
) -> BountyDetail:
    viewer_key = str(viewer.id) if viewer else f"ip:{client_ip(request)}"
    return await service.get_bounty(session, bounty_ref, viewer, viewer_key=viewer_key)


@router.patch("/{bounty_id}", response_model=BountyDetail)
async def update(
    bounty_id: uuid.UUID, data: BountyUpdate, session: SessionDep, user: CurrentUser
) -> BountyDetail:
    return await service.update_bounty(session, user, bounty_id, data)


@router.post("/{bounty_id}/publish", response_model=BountyDetail)
async def publish(bounty_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> BountyDetail:
    return await service.publish(session, user, bounty_id)


@router.post("/{bounty_id}/cancel", response_model=BountyDetail)
async def cancel(
    bounty_id: uuid.UUID, data: CancelRequest, session: SessionDep, user: CurrentUser
) -> BountyDetail:
    return await service.cancel(session, user, bounty_id, data.reason)


@router.post("/{bounty_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def bookmark(bounty_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    await service.bookmark(session, user, bounty_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{bounty_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def unbookmark(bounty_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    await service.unbookmark(session, user, bounty_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ReportCreated(APIModel):
    id: uuid.UUID


@router.post(
    "/{bounty_id}/report",
    response_model=ReportCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("bounty:report", 20, 3600))],
)
async def report(
    bounty_id: uuid.UUID,
    data: ReportRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.REPORT_CREATE))],
) -> ReportCreated:
    from app.modules.admin.service import create_report  # admin module owns report persistence

    bounty = await service.repo.get(session, bounty_id)
    if bounty is None or not service.can_view(bounty, user):
        raise NotFound("Bounty not found.")
    created = await create_report(
        session, reporter=user, target_type=ReportTarget.BOUNTY, target_id=bounty_id, reason=data.reason
    )
    await session.commit()
    return ReportCreated(id=created.id)


@router.get("/{bounty_ref}/activity", response_model=Page[ActivityItem])
async def activity(
    bounty_ref: str, session: SessionDep, viewer: OptionalUser, params: Annotated[PageParams, Depends()]
) -> Page[ActivityItem]:
    return await service.activity(session, bounty_ref, viewer, params)


@router.post("/{bounty_id}/feature", response_model=BountyDetail)
async def feature(
    bounty_id: uuid.UUID,
    data: FeatureRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.BOUNTY_FEATURE))],
) -> BountyDetail:
    return await service.set_featured(session, user, bounty_id, data.featured)
