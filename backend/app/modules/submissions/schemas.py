"""Submission schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.core.schemas import APIModel, UrlStr, UserSummary
from app.modules.applications.schemas import ApplicationBounty
from app.modules.payments.schemas import PaymentRecordOut
from app.modules.submissions.models import SubmissionStatus


class SubmissionCreate(APIModel):
    description: str = Field(min_length=20, max_length=20_000)
    evidence_url: UrlStr | None = None
    evidence_links: list[UrlStr] = Field(default_factory=list, max_length=10)

    @field_validator("description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class SubmissionUpdate(APIModel):
    description: str | None = Field(default=None, min_length=20, max_length=20_000)
    evidence_url: UrlStr | None = None
    evidence_links: list[UrlStr] | None = Field(default=None, max_length=10)


class FeedbackRequest(APIModel):
    feedback: str = Field(min_length=5, max_length=5000)


class ApproveRequest(APIModel):
    feedback: str | None = Field(default=None, max_length=5000)


class RejectRequest(APIModel):
    reason: str = Field(min_length=5, max_length=5000)


class RevisionOut(APIModel):
    version: int
    description: str
    evidence_url: str | None
    evidence_links: list[str]
    created_at: datetime


class SubmissionOut(APIModel):
    id: uuid.UUID
    bounty_id: uuid.UUID
    bounty: ApplicationBounty
    contributor: UserSummary
    assignment_id: uuid.UUID
    version: int
    description: str
    evidence_url: str | None
    evidence_links: list[str]
    status: SubmissionStatus
    review_feedback: str | None
    reviewer: UserSummary | None
    reviewed_at: datetime | None
    payment: PaymentRecordOut | None
    revisions: list[RevisionOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
