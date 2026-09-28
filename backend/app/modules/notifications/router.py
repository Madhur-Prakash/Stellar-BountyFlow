"""In-app notification inbox and notification preference endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.schemas import PageParams
from app.dependencies import CurrentUser, SessionDep
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    NotificationPage,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=NotificationPage)
async def list_notifications(
    session: SessionDep,
    user: CurrentUser,
    params: Annotated[PageParams, Depends()],
    unread_only: Annotated[bool, Query()] = False,
) -> NotificationPage:
    return await service.list_notifications(session, user, params, unread_only=unread_only)


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def mark_all_read(session: SessionDep, user: CurrentUser) -> Response:
    await service.mark_all_read(session, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def mark_read(notification_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    await service.mark_read(session, user, notification_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/notification-preferences", response_model=NotificationPreferencesOut)
async def get_preferences(session: SessionDep, user: CurrentUser) -> NotificationPreferencesOut:
    return await service.get_preferences(session, user)


@router.patch("/notification-preferences", response_model=NotificationPreferencesOut)
async def update_preferences(
    data: NotificationPreferencesUpdate, session: SessionDep, user: CurrentUser
) -> NotificationPreferencesOut:
    return await service.update_preferences(session, user, data)
