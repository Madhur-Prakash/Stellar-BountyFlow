"""Bounty Q&A endpoints (public reads, signed-in writes) and the staff moderation endpoint."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.rate_limit import rate_limit
from app.core.rbac import Permission
from app.core.schemas import APIModel, PageParams
from app.dependencies import CurrentUser, OptionalUser, SessionDep, require_permission
from app.modules.qa import service
from app.modules.qa.schemas import (
    ModeratedPostOut,
    ModeratePostRequest,
    PostUpdate,
    QASort,
    QuestionCreate,
    QuestionPage,
    ReplyCreate,
    ReportPostRequest,
    ThreadOut,
    VoteOut,
)
from app.modules.users.models import User

router = APIRouter(tags=["qa"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

_post_limit = Depends(rate_limit("qa:post", 60, 3600))


class PostReported(APIModel):
    id: uuid.UUID


@router.get("/bounties/{bounty_ref}/questions", response_model=QuestionPage)
async def list_questions(
    bounty_ref: str,
    session: SessionDep,
    viewer: OptionalUser,
    params: Annotated[PageParams, Depends()],
    sort: Annotated[QASort, Query()] = QASort.NEWEST,
) -> QuestionPage:
    return await service.list_threads(session, bounty_ref, viewer, sort, params)


@router.post(
    "/bounties/{bounty_id}/questions",
    response_model=ThreadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_post_limit],
)
async def ask(
    bounty_id: uuid.UUID, data: QuestionCreate, session: SessionDep, user: CurrentUser
) -> ThreadOut:
    return await service.ask(session, user, bounty_id, data.body)


@router.post(
    "/qa/posts/{post_id}/replies",
    response_model=ThreadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_post_limit],
)
async def reply(post_id: uuid.UUID, data: ReplyCreate, session: SessionDep, user: CurrentUser) -> ThreadOut:
    return await service.reply(session, user, post_id, data.body)


@router.patch("/qa/posts/{post_id}", response_model=ThreadOut, dependencies=[_post_limit])
async def edit(post_id: uuid.UUID, data: PostUpdate, session: SessionDep, user: CurrentUser) -> ThreadOut:
    return await service.edit(session, user, post_id, data.body)


@router.delete("/qa/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete(post_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    await service.remove(session, user, post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/qa/posts/{post_id}/vote", response_model=VoteOut)
async def upvote(post_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> VoteOut:
    return await service.vote(session, user, post_id, up=True)


@router.delete("/qa/posts/{post_id}/vote", response_model=VoteOut)
async def remove_vote(post_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> VoteOut:
    return await service.vote(session, user, post_id, up=False)


@router.post("/qa/posts/{post_id}/accept", response_model=ThreadOut)
async def accept(post_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ThreadOut:
    return await service.set_accepted(session, user, post_id, accepted=True)


@router.delete("/qa/posts/{post_id}/accept", response_model=ThreadOut)
async def unaccept(post_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ThreadOut:
    return await service.set_accepted(session, user, post_id, accepted=False)


@router.post("/qa/posts/{post_id}/pin", response_model=ThreadOut)
async def pin(post_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ThreadOut:
    return await service.set_pinned(session, user, post_id, pinned=True)


@router.delete("/qa/posts/{post_id}/pin", response_model=ThreadOut)
async def unpin(post_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> ThreadOut:
    return await service.set_pinned(session, user, post_id, pinned=False)


@router.post(
    "/qa/posts/{post_id}/report",
    response_model=PostReported,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("qa:report", 20, 3600))],
)
async def report(
    post_id: uuid.UUID,
    data: ReportPostRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.REPORT_CREATE))],
) -> PostReported:
    created = await service.report(session, user, post_id, data.reason)
    return PostReported(id=created.id)


@admin_router.post("/qa/posts/{post_id}/moderate", response_model=ModeratedPostOut)
async def moderate(
    post_id: uuid.UUID,
    data: ModeratePostRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.BOUNTY_MODERATE))],
) -> ModeratedPostOut:
    return await service.moderate(session, user, post_id, data.action, data.reason)
