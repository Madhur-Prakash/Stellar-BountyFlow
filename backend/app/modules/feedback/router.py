"""Feedback endpoints: one public submission route and the staff queue behind it."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.core.rate_limit import rate_limit
from app.core.rbac import Permission
from app.core.schemas import PageParams
from app.dependencies import OptionalUser, SessionDep, require_permission
from app.modules.feedback import service
from app.modules.feedback.models import FeedbackKind, FeedbackStatus
from app.modules.feedback.schemas import (
    FeedbackCreate,
    FeedbackOut,
    FeedbackPage,
    FeedbackReceived,
    HandleFeedbackRequest,
)
from app.modules.users.models import User

router = APIRouter(tags=["feedback"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# 5 per hour per IP. A person writing in good faith sends one note, and the extra four leave room for a second
# thought and for retries after a failed request; a script is held to 120 rows a day from one address. Nothing
# is emailed on arrival, so the only cost of abuse is rows in one table, and a limit tighter than this would
# start turning away colleagues behind a shared office address.
_submit_limit = Depends(rate_limit("feedback:submit", 5, 3600))


@router.post(
    "/feedback",
    response_model=FeedbackReceived,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_submit_limit],
)
async def submit(
    data: FeedbackCreate, request: Request, session: SessionDep, sender: OptionalUser
) -> FeedbackReceived:
    """Public: anyone may send feedback. A session, when there is one, records who sent it."""
    created = await service.submit(session, sender, data, request.headers.get("user-agent"))
    return FeedbackReceived(id=created.id)


@admin_router.get("/feedback", response_model=FeedbackPage)
async def list_feedback(
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.FEEDBACK_REVIEW))],
    params: Annotated[PageParams, Depends()],
    kind: Annotated[FeedbackKind | None, Query()] = None,
    status_filter: Annotated[FeedbackStatus | None, Query(alias="status")] = None,
) -> FeedbackPage:
    return await service.list_feedback(session, params, kind=kind, status=status_filter)


@admin_router.post("/feedback/{feedback_id}/handle", response_model=FeedbackOut)
async def handle(
    feedback_id: uuid.UUID,
    data: HandleFeedbackRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.FEEDBACK_REVIEW))],
) -> FeedbackOut:
    return await service.set_handled(session, user, feedback_id, data.handled, data.note)
