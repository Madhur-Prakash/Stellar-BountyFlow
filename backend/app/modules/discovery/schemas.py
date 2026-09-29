"""Saved search, recommendation and skill graph schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from app.core.schemas import APIModel, Page
from app.modules.bounties.schemas import BountySummary, MarketplaceFilters
from app.modules.discovery.models import AlertFrequency
from app.modules.users.schemas import normalize_tags

MAX_SAVED_SEARCHES = 25


class SavedSearchFilters(MarketplaceFilters):
    """The marketplace filters as saved. Every marketplace field is inherited, so a filter added to the
    marketplace is saved (and matched) without changes here. The deadline is kept as a rolling window
    ("closes within 7 days"), because fixed dates would make the search go stale."""

    deadline_within_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("q")
    @classmethod
    def _query(cls, v: str | None) -> str | None:
        v = v.replace("\x00", "").strip() if v else v
        return v or None

    @field_validator("skills", "tags")
    @classmethod
    def _names(cls, v: list[str] | None) -> list[str] | None:
        if not v:
            return None
        return normalize_tags(v, max_items=20) or None

    @model_validator(mode="after")
    def _rolling_deadline(self) -> SavedSearchFilters:
        if self.deadline_before is not None or self.deadline_after is not None:
            raise ValueError("Saved searches keep the deadline as deadline_within_days")
        return self

    def to_marketplace(self, now: datetime) -> MarketplaceFilters:
        """The exact filters the marketplace would apply for this search at ``now``."""
        data = self.model_dump(exclude={"deadline_within_days"})
        if self.deadline_within_days:
            data["deadline_after"] = now
            data["deadline_before"] = now + timedelta(days=self.deadline_within_days)
        return MarketplaceFilters.model_validate(data)

    def stored(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_stored(cls, data: dict[str, Any] | None) -> SavedSearchFilters:
        """Tolerant load: a stored value the current schema no longer accepts (a retired category, say) is
        dropped instead of making the whole search unreadable."""
        values = dict(data or {})
        for _ in range(len(values) + 1):
            try:
                return cls.model_validate(values)
            except ValidationError as exc:
                bad = {str(err["loc"][0]) for err in exc.errors() if err.get("loc")}
                if not bad or not bad & values.keys():
                    break
                for key in bad:
                    values.pop(key, None)
        return cls()


class _SavedSearchFields(APIModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class SavedSearchCreate(_SavedSearchFields):
    name: str = Field(min_length=1, max_length=80)
    filters: SavedSearchFilters = Field(default_factory=SavedSearchFilters)
    alert_frequency: AlertFrequency = AlertFrequency.INSTANT
    notify_in_app: bool = True
    notify_email: bool = True


class SavedSearchUpdate(_SavedSearchFields):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    filters: SavedSearchFilters | None = None
    alert_frequency: AlertFrequency | None = None
    notify_in_app: bool | None = None
    notify_email: bool | None = None
    is_paused: bool | None = None


class SavedSearchOut(APIModel):
    id: uuid.UUID
    name: str
    filters: SavedSearchFilters
    alert_frequency: AlertFrequency
    notify_in_app: bool
    notify_email: bool
    is_paused: bool
    new_count: int  # bounties that newly matched since the user last opened this search
    last_viewed_at: datetime
    next_digest_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UnsubscribeRequest(APIModel):
    token: str = Field(min_length=20, max_length=300)


class UnsubscribeResult(APIModel):
    saved_search_id: uuid.UUID
    name: str
    alert_frequency: AlertFrequency


class DigestRunRequest(APIModel):
    frequency: Literal["DAILY", "WEEKLY"]


class DigestRunResult(APIModel):
    frequency: str
    users: int
    searches: int
    matches: int


# --- Recommendations ------------------------------------------------------------------


class RelatedMatchOut(APIModel):
    skill: str  # the bounty's skill
    via: str  # the user's skill it is connected to in the graph


class RecommendationReason(APIModel):
    matched_skills: list[str]
    related_skills: list[RelatedMatchOut]


class Recommendation(APIModel):
    bounty: BountySummary
    score: float
    reason: RecommendationReason


class RecommendationPage(Page[Recommendation]):
    seed_skills: list[str]  # the user's strongest skills the ranking started from
    has_profile_skills: bool


class RelatedSkill(APIModel):
    skill: str
    weight: float
    via: list[str]
    # Raw skill names to filter the marketplace by; empty when no bounty requires this skill (only tags use it).
    marketplace_skills: list[str]


class RelatedSkills(APIModel):
    skills: list[str]
    related: list[RelatedSkill]
    computed_at: datetime | None
