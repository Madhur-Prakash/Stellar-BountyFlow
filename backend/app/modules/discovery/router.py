"""Discovery endpoints: saved searches and their alerts, recommendations, and related skills."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.core.rate_limit import rate_limit
from app.core.rbac import Permission
from app.core.schemas import PageParams
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.bounties.router import marketplace_filters
from app.modules.bounties.schemas import MarketplaceFilters
from app.modules.discovery import recommendations, saved_searches
from app.modules.discovery.models import AlertFrequency
from app.modules.discovery.schemas import (
    DigestRunRequest,
    DigestRunResult,
    RecommendationPage,
    RelatedSkills,
    SavedSearchCreate,
    SavedSearchOut,
    SavedSearchUpdate,
    UnsubscribeRequest,
    UnsubscribeResult,
)
from app.modules.users.models import User

router = APIRouter(tags=["discovery"])


@router.get("/saved-searches", response_model=list[SavedSearchOut])
async def list_saved_searches(session: SessionDep, user: CurrentUser) -> list[SavedSearchOut]:
    return await saved_searches.list_searches(session, user)


@router.post(
    "/saved-searches",
    response_model=SavedSearchOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("saved_search:create", 60, 3600))],
)
async def create_saved_search(
    data: SavedSearchCreate, session: SessionDep, user: CurrentUser
) -> SavedSearchOut:
    return await saved_searches.create_search(session, user, data)


@router.post("/saved-searches/unsubscribe", response_model=UnsubscribeResult)
async def unsubscribe(data: UnsubscribeRequest, session: SessionDep) -> UnsubscribeResult:
    """Public and CSRF-exempt: authorised by the signed token from the alert email, and it can only turn alerts
    off."""
    return await saved_searches.unsubscribe(session, data.token)


@router.get("/saved-searches/{search_id}", response_model=SavedSearchOut)
async def get_saved_search(search_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> SavedSearchOut:
    return await saved_searches.get_search(session, user, search_id)


@router.patch("/saved-searches/{search_id}", response_model=SavedSearchOut)
async def update_saved_search(
    search_id: uuid.UUID, data: SavedSearchUpdate, session: SessionDep, user: CurrentUser
) -> SavedSearchOut:
    return await saved_searches.update_search(session, user, search_id, data)


@router.delete("/saved-searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_saved_search(search_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    await saved_searches.delete_search(session, user, search_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/saved-searches/{search_id}/viewed", response_model=SavedSearchOut)
async def mark_saved_search_viewed(
    search_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> SavedSearchOut:
    return await saved_searches.mark_viewed(session, user, search_id)


@router.get("/recommendations", response_model=RecommendationPage)
async def list_recommendations(
    session: SessionDep,
    user: CurrentUser,
    filters: Annotated[MarketplaceFilters, Depends(marketplace_filters)],
    params: Annotated[PageParams, Depends()],
) -> RecommendationPage:
    return await recommendations.recommend(session, user, filters, params)


@router.get("/skills/related", response_model=RelatedSkills)
async def related_skills(
    session: SessionDep,
    skills: Annotated[str, Query(min_length=1, max_length=600)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> RelatedSkills:
    names = [s.strip() for s in skills.split(",") if s.strip()][:20]
    return await recommendations.related(session, names, limit)


@router.post("/admin/discovery/digests/run", response_model=DigestRunResult)
async def run_digests_now(
    data: DigestRunRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.USER_MANAGE))],
) -> DigestRunResult:
    """Sends every pending digest of one frequency now, ignoring the schedule. Exists only when
    DISCOVERY_DIGEST_TRIGGER_ENABLED is set (end-to-end tests, operators); otherwise it answers 404."""
    if not get_settings().discovery_digest_trigger_enabled:
        raise NotFound("Not found.")
    return await saved_searches.run_digests(session, AlertFrequency(data.frequency), force=True)
