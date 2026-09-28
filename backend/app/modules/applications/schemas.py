"""Application schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.core.schemas import APIModel, UrlStr, UserSummary
from app.modules.applications.models import ApplicationStatus
from app.modules.bounties.models import BountyStatus


class ApplicationCreate(APIModel):
    cover_message: str = Field(min_length=20, max_length=5000)
    relevant_experience: str | None = Field(default=None, max_length=5000)
    work_samples: list[UrlStr] = Field(default_factory=list, max_length=10)

    @field_validator("cover_message", "relevant_experience")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None


class ReviewNote(APIModel):
    note: str | None = Field(default=None, max_length=2000)


class ApplicationBounty(APIModel):
    id: uuid.UUID
    slug: str
    title: str
    status: BountyStatus


class ContributorSummary(UserSummary):
    skills: list[str]


class ApplicationOut(APIModel):
    id: uuid.UUID
    bounty_id: uuid.UUID
    bounty: ApplicationBounty
    contributor: ContributorSummary
    cover_message: str
    relevant_experience: str | None
    work_samples: list[str]
    status: ApplicationStatus
    review_note: str | None
    assignment_id: uuid.UUID | None = None
    onchain_assigned: bool = False  # the contributor is locked in the escrow contract via ASSIGN
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
