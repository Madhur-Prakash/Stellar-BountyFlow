"""Escrow v2 request/response schemas: milestones, the on-chain review clock and the arbiter panel."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.core.schemas import APIModel, Money, MoneyInput, OptionalMoney, UserSummary
from app.modules.escrow.models import MilestoneStatus
from app.modules.submissions.models import OnchainReviewState

MIN_MILESTONES = 2
MAX_MILESTONES = 20


class MilestoneInput(APIModel):
    title: str = Field(min_length=3, max_length=140)
    description: str | None = Field(default=None, max_length=2000)
    amount: MoneyInput

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class MilestonesUpdate(APIModel):
    """Replaces a draft bounty's milestones. An empty list removes them (one reward per position again)."""

    milestones: list[MilestoneInput] = Field(default_factory=list, max_length=MAX_MILESTONES)


class MilestoneOut(APIModel):
    id: uuid.UUID
    position: int
    title: str
    description: str | None
    amount: Money
    status: MilestoneStatus
    paid_at: datetime | None
    payout_transaction_id: uuid.UUID | None
    explorer_url: str | None = None


class SubmissionMilestone(APIModel):
    id: uuid.UUID
    position: int
    title: str
    amount: Money
    status: MilestoneStatus


class OnchainReviewOut(APIModel):
    """The contract's review clock for one submission (all times from verified chain state)."""

    state: OnchainReviewState
    submitted_at: datetime | None
    claimable_at: datetime | None
    # Server-side view of the rules at response time; the contract has the final word.
    can_claim: bool = False
    can_answer: bool = False


class EscrowConfigOut(APIModel):
    contract_id: str | None
    contract_version: int
    default_review_window_seconds: int
    min_review_window_seconds: int
    max_review_window_seconds: int
    arbiter_addresses: list[str]
    arbiter_threshold: int
    max_milestones: int = MAX_MILESTONES
    max_batch: int


class ArbiterOut(APIModel):
    address: str
    staff: UserSummary | None  # the staff account that verified this arbiter wallet, if any
    approved: bool
    contributor_amount: OptionalMoney = None  # what this arbiter approved in the current round


class ArbitrationOut(APIModel):
    dispute_id: uuid.UUID
    contract_version: int
    escrow_frozen: bool
    executed: bool
    round: int
    threshold: int
    approvals: int  # current-round approvals of the recorded resolution
    arbiters: list[ArbiterOut]
    resolution: str | None
    contributor_amount: OptionalMoney = None  # what the recorded resolution pays the contributor
    requester_amount: OptionalMoney = None  # what returns to the requester
    position_value: OptionalMoney = None  # the contributor's open reward on-chain
    my_arbiter_wallets: list[str] = Field(default_factory=list)
    my_vote_recorded: bool = False
    can_vote: bool = False
    vote_blocked_reason: str | None = None
