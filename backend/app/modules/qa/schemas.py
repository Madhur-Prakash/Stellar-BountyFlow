"""Bounty Q&A schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from app.core.schemas import APIModel, Page, UserSummary

# Body limits (characters). Markdown is stored raw and rendered by the SPA without raw HTML.
QUESTION_MIN = 10
REPLY_MIN = 2
BODY_MAX = 5000


class QASort(StrEnum):
    NEWEST = "newest"
    HELPFUL = "helpful"  # most upvotes first


class _Body(APIModel):
    @field_validator("body", mode="before", check_fields=False)
    @classmethod
    def _clean(cls, value: object) -> object:
        # Trimmed before the length limits apply; PostgreSQL text cannot hold NUL bytes.
        return value.replace("\x00", "").strip() if isinstance(value, str) else value


class QuestionCreate(_Body):
    body: str = Field(min_length=QUESTION_MIN, max_length=BODY_MAX)


class ReplyCreate(_Body):
    body: str = Field(min_length=REPLY_MIN, max_length=BODY_MAX)


class PostUpdate(_Body):
    body: str = Field(min_length=REPLY_MIN, max_length=BODY_MAX)


class ReportPostRequest(APIModel):
    reason: str = Field(min_length=10, max_length=2000)


class ModeratePostRequest(APIModel):
    action: Literal["HIDE", "UNHIDE"]
    reason: str = Field(min_length=5, max_length=1000)


class PostOut(APIModel):
    id: uuid.UUID
    question_id: uuid.UUID  # the thread: the question's own id for a question
    parent_id: uuid.UUID | None
    author: UserSummary | None  # None once deleted
    # None when the post is deleted, or hidden and the viewer is neither its author nor a moderator.
    body: str | None
    is_requester: bool  # written by the bounty's requester
    is_mine: bool = False
    is_pinned: bool = False
    is_accepted: bool = False
    upvotes: int = 0
    viewer_voted: bool = False
    is_deleted: bool = False
    is_hidden: bool = False
    hidden_reason: str | None = None  # only for the author and moderators
    edited_at: datetime | None
    created_at: datetime


class ThreadOut(PostOut):
    replies: list[PostOut] = Field(default_factory=list)
    reply_count: int = 0
    answered: bool = False  # the requester replied, or a reply was accepted


class QuestionPage(Page[ThreadOut]):
    questions_count: int
    can_ask: bool
    closed_reason: str | None
    viewer_is_requester: bool
    viewer_is_moderator: bool


class VoteOut(APIModel):
    post_id: uuid.UUID
    upvotes: int
    viewer_voted: bool


class ModeratedPostOut(PostOut):
    bounty_id: uuid.UUID
    bounty_slug: str
