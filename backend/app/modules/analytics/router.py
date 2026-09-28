"""Analytics endpoints: public marketplace stats, personal dashboards, and platform metrics."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.rbac import Permission
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    ContributorAnalytics,
    MyAnalytics,
    PlatformAnalytics,
    PublicStats,
    RequesterAnalytics,
)
from app.modules.users.models import User

router = APIRouter(prefix="/analytics", tags=["analytics"])

PlatformAnalyst = Annotated[User, Depends(require_permission(Permission.ANALYTICS_PLATFORM))]


@router.get("/public", response_model=PublicStats)
async def public_stats(session: SessionDep) -> PublicStats:
    return await service.get_public_stats(session)


@router.get("/me", response_model=MyAnalytics)
async def my_analytics(session: SessionDep, user: CurrentUser) -> MyAnalytics:
    return await service.my_analytics(session, user)


@router.get("/requester", response_model=RequesterAnalytics)
async def requester_analytics(session: SessionDep, user: CurrentUser) -> RequesterAnalytics:
    return await service.requester_analytics(session, user)


@router.get("/contributor", response_model=ContributorAnalytics)
async def contributor_analytics(session: SessionDep, user: CurrentUser) -> ContributorAnalytics:
    return await service.contributor_analytics(session, user)


@router.get("/platform", response_model=PlatformAnalytics)
async def platform_analytics(session: SessionDep, user: PlatformAnalyst) -> PlatformAnalytics:
    return await service.platform_analytics(session)
