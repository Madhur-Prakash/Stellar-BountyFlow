"""Admin and moderation API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.core.schemas import APIModel, UserSummary
from app.modules.admin.models import ReportStatus, ReportTarget
from app.modules.users.models import Role

HealthState = Literal["ok", "error", "disabled"]


class AdminUserOut(UserSummary):
    email: str
    role: Role
    is_active: bool
    email_verified: bool
    last_login_at: datetime | None
    created_at: datetime


class AdminUserUpdate(APIModel):
    is_active: bool | None = None
    role: Role | None = None


class ReportTargetSummary(APIModel):
    """Context a moderator needs beside a report (filled for Q&A posts)."""

    label: str
    excerpt: str | None = None
    link: str | None = None
    author: UserSummary | None = None
    is_hidden: bool = False
    is_deleted: bool = False
    bounty_id: uuid.UUID | None = None


class ReportOut(APIModel):
    id: uuid.UUID
    reporter: UserSummary
    target_type: ReportTarget
    target_id: uuid.UUID
    reason: str
    status: ReportStatus
    created_at: datetime
    resolution_note: str | None
    resolved_at: datetime | None
    target_summary: ReportTargetSummary | None = None


class ReportResolve(APIModel):
    status: Literal[ReportStatus.ACTIONED, ReportStatus.DISMISSED]
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A resolution note is required")
        return value


class AuditLogOut(APIModel):
    id: uuid.UUID
    actor: UserSummary | None
    action: str
    entity_type: str
    entity_id: uuid.UUID
    bounty_id: uuid.UUID | None
    metadata: dict[str, Any]
    created_at: datetime


class OverviewCounts(APIModel):
    users_total: int
    users_active_30d: int
    users_suspended: int
    bounties_total: int
    bounties_open: int
    bounties_hidden: int
    open_reports: int
    open_disputes: int
    pending_transactions: int
    failed_transactions_24h: int
    unpublished_outbox_events: int


class HealthSnapshot(APIModel):
    database: HealthState
    redis: HealthState
    kafka: HealthState
    blockchain_rpc: HealthState
    worker: HealthState


class AdminOverview(APIModel):
    generated_at: datetime
    network: str
    counts: OverviewCounts
    health: HealthSnapshot
    worker_heartbeat_at: datetime | None
