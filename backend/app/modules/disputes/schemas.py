"""Dispute schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import APIModel, MoneyInput, OptionalMoney, UrlStr, UserSummary
from app.modules.bounties.schemas import ActivityBounty
from app.modules.disputes.models import DisputeResolution, DisputeStatus


class DisputeCreate(APIModel):
    reason: str = Field(min_length=20, max_length=5000)
    evidence_url: UrlStr | None = None
    contributor_id: uuid.UUID | None = None  # required when the requester raises it and several are assigned


class EvidenceCreate(APIModel):
    description: str = Field(min_length=5, max_length=5000)
    url: UrlStr | None = None


class ResolveRequest(APIModel):
    resolution: DisputeResolution
    note: str = Field(min_length=10, max_length=5000)
    # SPLIT only: what the contributor receives; the rest of their position returns to the requester.
    contributor_amount: MoneyInput | None = None


class EvidenceOut(APIModel):
    id: uuid.UUID
    submitted_by: UserSummary
    description: str
    url: str | None
    created_at: datetime


class DisputeOut(APIModel):
    id: uuid.UUID
    bounty: ActivityBounty
    raised_by: UserSummary
    contributor: UserSummary | None
    reason: str
    status: DisputeStatus
    assigned_moderator: UserSummary | None
    resolution: DisputeResolution | None
    resolution_note: str | None
    evidence: list[EvidenceOut]
    escrow_frozen_onchain: bool
    requires_onchain_execution: bool
    created_at: datetime
    resolved_at: datetime | None
    # Escrow v2: the M-of-N arbiter set of the escrow and the confirmed approvals of the current round.
    contract_version: int = 1
    arbiter_threshold: int = 1
    arbiter_approvals: int = 0
    contributor_amount: OptionalMoney = None
