"""Application endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status

from app.core.rate_limit import rate_limit
from app.core.rbac import Permission
from app.core.schemas import Page, PageParams
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.applications import service
from app.modules.applications.models import ApplicationStatus
from app.modules.applications.schemas import ApplicationCreate, ApplicationOut, ReviewNote
from app.modules.users.models import User

router = APIRouter(tags=["applications"])


@router.post(
    "/bounties/{bounty_id}/applications",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("application:create", 60, 3600))],
)
async def apply(
    bounty_id: uuid.UUID,
    data: ApplicationCreate,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.APPLICATION_CREATE))],
) -> ApplicationOut:
    return await service.apply(session, user, bounty_id, data)


@router.get("/bounties/{bounty_id}/applications", response_model=Page[ApplicationOut])
async def list_for_bounty(
    bounty_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
) -> Page[ApplicationOut]:
    return await service.list_for_bounty(session, user, bounty_id, status_filter, params)


@router.get("/applications/me", response_model=Page[ApplicationOut])
async def my_applications(
    session: SessionDep,
    user: CurrentUser,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
) -> Page[ApplicationOut]:
    return await service.my_applications(session, user, status_filter, params)


@router.post("/applications/{application_id}/withdraw", response_model=ApplicationOut)
async def withdraw(application_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ApplicationOut:
    return await service.withdraw(session, user, application_id)


@router.post("/applications/{application_id}/accept", response_model=ApplicationOut)
async def accept(
    application_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    data: Annotated[ReviewNote | None, Body()] = None,
) -> ApplicationOut:
    return await service.accept(session, user, application_id, data.note if data else None)


@router.post("/applications/{application_id}/reject", response_model=ApplicationOut)
async def reject(
    application_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    data: Annotated[ReviewNote | None, Body()] = None,
) -> ApplicationOut:
    return await service.reject(session, user, application_id, data.note if data else None)
