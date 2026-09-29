"""Feedback API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.core.schemas import APIModel, Page, UserSummary
from app.modules.feedback.models import FeedbackKind, FeedbackStatus

MESSAGE_MIN = 10
MESSAGE_MAX = 2000
PATH_MAX = 200
NOTE_MAX = 2000
# Wider than any real display; enough to tell a phone from a desktop without pretending to be precise.
VIEWPORT_MAX = 20_000


class FeedbackCreate(APIModel):
    """What the form sends. The user agent is read from the request header, not from the page."""

    kind: FeedbackKind
    message: str = Field(min_length=MESSAGE_MIN, max_length=MESSAGE_MAX)
    # Signed-out senders only; ignored when a session identifies the sender.
    email: EmailStr | None = Field(default=None, max_length=320)
    # The route the sender was on, e.g. "/bounties/fix-the-thing". Query strings are dropped (see below).
    path: str | None = Field(default=None, max_length=PATH_MAX)
    viewport_width: int | None = Field(default=None, ge=0, le=VIEWPORT_MAX)
    viewport_height: int | None = Field(default=None, ge=0, le=VIEWPORT_MAX)

    @field_validator("message", mode="before")
    @classmethod
    def _clean_message(cls, value: object) -> object:
        # Trimmed before the length limits apply; PostgreSQL text cannot hold NUL bytes.
        return value.replace("\x00", "").strip() if isinstance(value, str) else value

    @field_validator("path", mode="before")
    @classmethod
    def _clean_path(cls, value: object) -> object:
        """Keep the route and nothing else.

        A query string or fragment can carry what someone typed into a search box, so it is cut off here rather
        than trusted not to be sent. Anything that is not a site-relative path becomes ``None``.
        """
        if not isinstance(value, str):
            return value
        path = value.split("?", 1)[0].split("#", 1)[0].strip()
        if not path.startswith("/") or path.startswith("//"):
            return None
        return path[:PATH_MAX]


class FeedbackReceived(APIModel):
    id: uuid.UUID


class FeedbackOut(APIModel):
    id: uuid.UUID
    kind: FeedbackKind
    status: FeedbackStatus
    message: str
    sender: UserSummary | None
    email: str | None  # a signed-out sender's reply address, when they left one
    path: str | None
    viewport_width: int | None
    viewport_height: int | None
    user_agent: str | None
    created_at: datetime
    handled_at: datetime | None
    handled_by: UserSummary | None
    handled_note: str | None


class FeedbackPage(Page[FeedbackOut]):
    """The page, plus how much is still waiting (across every filter)."""

    new_count: int


class HandleFeedbackRequest(APIModel):
    handled: bool = True
    note: str | None = Field(default=None, max_length=NOTE_MAX)

    @field_validator("note", mode="before")
    @classmethod
    def _clean_note(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.replace("\x00", "").strip() or None
