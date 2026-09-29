"""Request and response schemas for data exports, account deletion, legal versions and screening."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.core.schemas import APIModel, UserSummary
from app.modules.compliance.models import (
    DeletionStatus,
    ExportStatus,
    LegalDocument,
    ScreeningSource,
)

# --- Data export ---------------------------------------------------------------------------


class DataExportOut(APIModel):
    id: uuid.UUID
    status: ExportStatus
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    size_bytes: int | None
    download_count: int
    # A signed link that works for a few minutes, only for READY exports (fetch the list again for a new one).
    download_url: str | None = None


# --- Account deletion ----------------------------------------------------------------------


class BlockerOut(APIModel):
    kind: str
    message: str
    count: int
    links: list[str]


class DeletionRequestOut(APIModel):
    id: uuid.UUID
    status: DeletionStatus
    created_at: datetime
    scheduled_for: datetime
    cancelled_at: datetime | None
    completed_at: datetime | None
    blocked_reason: str | None


class DeletionStatusOut(APIModel):
    request: DeletionRequestOut | None
    blockers: list[BlockerOut]
    grace_days: int


class DeletionCreate(APIModel):
    password: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=500)


class AdminDeletionRequestOut(DeletionRequestOut):
    user: UserSummary
    email: str
    reason: str | None
    pseudonym: str | None
    last_attempt_at: datetime | None
    blockers: list[BlockerOut]


# --- Legal documents -----------------------------------------------------------------------


class LegalVersionOut(APIModel):
    id: uuid.UUID
    document: LegalDocument
    version: str
    summary: str
    effective_at: datetime
    created_at: datetime
    withdrawn_at: datetime | None


class LegalDocumentStatus(APIModel):
    document: LegalDocument
    current: LegalVersionOut | None
    upcoming: LegalVersionOut | None
    accepted_current: bool
    accepted_upcoming: bool
    accepted_at: datetime | None


class LegalStatusOut(APIModel):
    documents: list[LegalDocumentStatus]
    # The workspace is gated until the user accepts the versions in effect.
    needs_acceptance: bool
    # A newer version is scheduled and has not been accepted yet (a notice, not a gate).
    upcoming_pending: bool


class LegalAccept(APIModel):
    version_ids: list[uuid.UUID] = Field(min_length=1, max_length=4)


class LegalVersionCreate(APIModel):
    document: LegalDocument
    version: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")
    summary: str = Field(min_length=10, max_length=2000)
    # Omit to put the version in effect immediately.
    effective_at: datetime | None = None


class AdminLegalVersionOut(LegalVersionOut):
    published_by: UserSummary | None
    accepted_count: int


# --- Screening -----------------------------------------------------------------------------


class ScreeningEntryCreate(APIModel):
    address: str = Field(min_length=56, max_length=56)
    reason: str = Field(min_length=3, max_length=500)


class ScreeningEntryRemove(APIModel):
    note: str = Field(min_length=3, max_length=500)


class ScreeningEntryOut(APIModel):
    id: uuid.UUID
    address: str
    source: ScreeningSource
    list_name: str
    reason: str | None
    created_at: datetime
    added_by: UserSummary | None
    removed_at: datetime | None
    removal_note: str | None


class ScreeningDecisionOut(APIModel):
    id: uuid.UUID
    created_at: datetime
    result: str  # "blocked" | "cleared"
    address: str
    context: str
    provider: str
    user: UserSummary | None
    matches: list[dict[str, Any]]
    bounty_id: str | None
    request_id: str | None


class ScreeningListStatus(APIModel):
    configured: bool
    name: str
    source: str | None = None
    format: str | None = None
    entries: int = 0
    loaded_at: datetime | None = None
    checked_at: datetime | None = None
    error: str | None = None


class ScreeningStatusOut(APIModel):
    enabled: bool
    provider: str
    manual_entries: int
    list_entries: int
    list: ScreeningListStatus
