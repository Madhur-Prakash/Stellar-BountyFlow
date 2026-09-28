"""Submission endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, status

from app.core.rate_limit import rate_limit
from app.core.schemas import Page, PageParams
from app.dependencies import CurrentUser, SessionDep
from app.modules.submissions import service
from app.modules.submissions.models import SubmissionStatus
from app.modules.submissions.schemas import (
    ApproveRequest,
    FeedbackRequest,
    RejectRequest,
    SubmissionCreate,
    SubmissionOut,
    SubmissionUpdate,
)

router = APIRouter(tags=["submissions"])


@router.post(
    "/bounties/{bounty_id}/submissions",
    response_model=SubmissionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("submission:create", 30, 3600))],
)
async def create(
    bounty_id: uuid.UUID, data: SubmissionCreate, session: SessionDep, user: CurrentUser
) -> SubmissionOut:
    return await service.create(session, user, bounty_id, data)


@router.get("/bounties/{bounty_id}/submissions", response_model=Page[SubmissionOut])
async def list_for_bounty(
    bounty_id: uuid.UUID, session: SessionDep, user: CurrentUser, params: Annotated[PageParams, Depends()]
) -> Page[SubmissionOut]:
    return await service.list_for_bounty(session, user, bounty_id, params)


@router.get("/submissions/me", response_model=Page[SubmissionOut])
async def mine(
    session: SessionDep,
    user: CurrentUser,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[SubmissionStatus | None, Query(alias="status")] = None,
) -> Page[SubmissionOut]:
    return await service.mine(session, user, status_filter, params)


@router.get("/submissions/{submission_id}", response_model=SubmissionOut)
async def get(submission_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> SubmissionOut:
    return await service.get(session, user, submission_id)


@router.patch("/submissions/{submission_id}", response_model=SubmissionOut)
async def update(
    submission_id: uuid.UUID, data: SubmissionUpdate, session: SessionDep, user: CurrentUser
) -> SubmissionOut:
    return await service.resubmit(session, user, submission_id, data)


@router.post("/submissions/{submission_id}/request-revision", response_model=SubmissionOut)
async def request_revision(
    submission_id: uuid.UUID, data: FeedbackRequest, session: SessionDep, user: CurrentUser
) -> SubmissionOut:
    return await service.request_revision(session, user, submission_id, data.feedback)


@router.post("/submissions/{submission_id}/approve", response_model=SubmissionOut)
async def approve(
    submission_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    data: Annotated[ApproveRequest | None, Body()] = None,
) -> SubmissionOut:
    return await service.approve(session, user, submission_id, data.feedback if data else None)


@router.post("/submissions/{submission_id}/reject", response_model=SubmissionOut)
async def reject(
    submission_id: uuid.UUID, data: RejectRequest, session: SessionDep, user: CurrentUser
) -> SubmissionOut:
    return await service.reject(session, user, submission_id, data.reason)
