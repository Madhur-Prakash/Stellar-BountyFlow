"""Bounty request/response schemas."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.core.schemas import APIModel, Asset, Money, MoneyInput, UrlStr, UserSummary
from app.modules.applications.models import ApplicationStatus
from app.modules.bounties.models import BountyStatus, Category, Difficulty, Visibility
from app.modules.escrow.schemas import MilestoneInput, MilestoneOut
from app.modules.users.schemas import normalize_tags


class FundingStatus(StrEnum):
    UNFUNDED = "UNFUNDED"
    PENDING = "PENDING"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FUNDED = "FUNDED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    SETTLED = "SETTLED"


class SortOption(StrEnum):
    RELEVANCE = "relevance"
    NEWEST = "newest"
    DEADLINE = "deadline"
    REWARD_HIGH = "reward_high"
    REWARD_LOW = "reward_low"
    POPULAR = "popular"


class Link(APIModel):
    label: str = Field(min_length=1, max_length=80)
    url: UrlStr


def _future(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


class _BountyContent(APIModel):
    title: str = Field(min_length=8, max_length=140)
    short_description: str = Field(min_length=20, max_length=280)
    description: str = Field(min_length=40, max_length=20_000)
    category: Category
    difficulty: Difficulty
    tags: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    application_deadline: datetime | None = None
    completion_deadline: datetime | None = None
    eligibility_criteria: str | None = Field(default=None, max_length=5000)
    submission_requirements: str | None = Field(default=None, max_length=5000)
    acceptance_criteria: str | None = Field(default=None, max_length=5000)
    repository_url: UrlStr | None = None
    links: list[Link] = Field(default_factory=list, max_length=10)
    # Approval then needs a merged pull request, verified through GitHub, from the contributor.
    require_merged_pr: bool = False
    visibility: Visibility = Visibility.PUBLIC

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return normalize_tags(v, max_items=10)

    @field_validator("required_skills")
    @classmethod
    def _skills(cls, v: list[str]) -> list[str]:
        return normalize_tags(v, max_items=15)

    @field_validator("title", "short_description", "description")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("application_deadline", "completion_deadline")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        return _future(v)


class BountyCreate(_BountyContent):
    reward_amount: MoneyInput
    # "native"/"XLM" or an enabled registry asset ("CODE:ISSUER", or its code when unambiguous).
    reward_asset: str | None = Field(default=None, max_length=80)
    positions_available: int = Field(default=1, ge=1, le=100)
    # Escrow v2: seconds the requester has to answer recorded work (None = the server default), and an optional
    # split of a single-position reward into milestones that add up to it.
    review_window_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    milestones: list[MilestoneInput] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _deadlines(self) -> BountyCreate:
        now = datetime.now(UTC)
        for name in ("application_deadline", "completion_deadline"):
            value = getattr(self, name)
            if value is not None and value <= now:
                raise ValueError(f"{name.replace('_', ' ').capitalize()} must be in the future")
        if (
            self.application_deadline
            and self.completion_deadline
            and (self.application_deadline > self.completion_deadline)
        ):
            raise ValueError("Application deadline must be before the completion deadline")
        return self


class BountyUpdate(APIModel):
    title: str | None = Field(default=None, min_length=8, max_length=140)
    short_description: str | None = Field(default=None, min_length=20, max_length=280)
    description: str | None = Field(default=None, min_length=40, max_length=20_000)
    category: Category | None = None
    difficulty: Difficulty | None = None
    tags: list[str] | None = None
    required_skills: list[str] | None = None
    reward_amount: MoneyInput | None = None
    reward_asset: str | None = Field(default=None, max_length=80)
    positions_available: int | None = Field(default=None, ge=1, le=100)
    application_deadline: datetime | None = None
    completion_deadline: datetime | None = None
    eligibility_criteria: str | None = Field(default=None, max_length=5000)
    submission_requirements: str | None = Field(default=None, max_length=5000)
    acceptance_criteria: str | None = Field(default=None, max_length=5000)
    repository_url: UrlStr | None = None
    links: list[Link] | None = Field(default=None, max_length=10)
    require_merged_pr: bool | None = None
    visibility: Visibility | None = None
    review_window_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    milestones: list[MilestoneInput] | None = Field(default=None, max_length=20)

    _tags = field_validator("tags")(classmethod(lambda cls, v: normalize_tags(v, max_items=10) if v else v))
    _skills = field_validator("required_skills")(
        classmethod(lambda cls, v: normalize_tags(v, max_items=15) if v else v)
    )

    @field_validator("application_deadline", "completion_deadline")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        return _future(v)


class CancelRequest(APIModel):
    reason: str = Field(min_length=5, max_length=1000)


class ReportRequest(APIModel):
    reason: str = Field(min_length=10, max_length=2000)


class FeatureRequest(APIModel):
    featured: bool


class ModerateRequest(APIModel):
    action: Literal["HIDE", "UNHIDE", "CANCEL"]
    reason: str = Field(min_length=5, max_length=1000)


class EscrowView(APIModel):
    contract_id: str | None
    network: str
    asset: Asset
    onchain_bounty_id: str
    required_amount: Money
    funded_amount: Money
    paid_out_amount: Money
    refunded_amount: Money
    state: str
    last_reconciled_at: datetime | None
    explorer_url: str | None = None
    # Escrow v2: the deployment this escrow lives on and its dispute terms.
    contract_version: int = 1
    arbiter_addresses: list[str] = Field(default_factory=list)
    arbiter_threshold: int = 1
    review_window_seconds: int | None = None


class BountySummary(APIModel):
    id: uuid.UUID
    slug: str
    title: str
    short_description: str
    category: Category
    difficulty: Difficulty
    tags: list[str]
    required_skills: list[str]
    reward_amount: Money
    reward_asset: Asset
    total_reward: Money
    network: str
    status: BountyStatus
    funding_status: FundingStatus
    application_deadline: datetime | None
    completion_deadline: datetime | None
    positions_available: int
    positions_filled: int
    applications_count: int
    requester: UserSummary
    is_featured: bool
    is_bookmarked: bool = False
    is_hidden: bool = False  # true only for moderator-hidden bounties (visible to owners and staff)
    created_at: datetime
    published_at: datetime | None
    questions_count: int = 0  # visible Q&A questions (modules/qa)


class ViewerApplication(APIModel):
    id: uuid.UUID
    status: ApplicationStatus


class Viewer(APIModel):
    is_owner: bool
    is_assigned: bool
    can_apply: bool
    can_submit: bool
    application: ViewerApplication | None
    assignment_id: uuid.UUID | None
    is_moderator: bool = False


class BountyDetail(BountySummary):
    description: str
    eligibility_criteria: str | None
    submission_requirements: str | None
    acceptance_criteria: str | None
    repository_url: str | None
    require_merged_pr: bool = False
    links: list[Link]
    visibility: Visibility
    escrow: EscrowView | None
    cancel_reason: str | None = None
    viewer: Viewer | None = None
    milestones: list[MilestoneOut] = Field(default_factory=list)
    review_window_seconds: int | None = None


class ActivityBounty(APIModel):
    id: uuid.UUID
    slug: str
    title: str


class ActivityItem(APIModel):
    id: uuid.UUID
    action: str
    actor: UserSummary | None
    entity_type: str
    entity_id: uuid.UUID
    bounty: ActivityBounty | None
    metadata: dict[str, Any]
    created_at: datetime
    link: str | None


class MarketplaceFilters(APIModel):
    q: str | None = Field(default=None, max_length=200)
    category: list[Category] | None = None
    skills: list[str] | None = None
    tags: list[str] | None = None
    difficulty: list[Difficulty] | None = None
    status: list[BountyStatus] | None = None
    min_reward: Decimal | None = Field(default=None, ge=0)
    max_reward: Decimal | None = Field(default=None, ge=0)
    deadline_before: datetime | None = None
    deadline_after: datetime | None = None
    funded_only: bool = False
    asset: list[str] | None = None  # reward asset identifiers ("native", "CODE:ISSUER")
    sort: SortOption | None = None

    @field_validator("q")
    @classmethod
    def _search_text(cls, v: str | None) -> str | None:
        # PostgreSQL text cannot contain NUL bytes: passing one through made the search query fail (500).
        return v.replace("\x00", "") if v else v

    def cache_key_params(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)
