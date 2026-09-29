"""Bounties, tags, required skills, bookmarks, and view counters."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import MONEY, Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.users.models import User


class BountyStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    FUNDING_PENDING = "FUNDING_PENDING"
    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMPLETED = "COMPLETED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"
    EXPIRED = "EXPIRED"


class Category(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    BUG_BOUNTY = "BUG_BOUNTY"
    DESIGN = "DESIGN"
    SECURITY = "SECURITY"
    DOCUMENTATION = "DOCUMENTATION"
    RESEARCH = "RESEARCH"
    COMMUNITY = "COMMUNITY"
    OTHER = "OTHER"


class Difficulty(StrEnum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class Visibility(StrEnum):
    PUBLIC = "PUBLIC"
    UNLISTED = "UNLISTED"


class Bounty(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "bounties"
    __table_args__ = (
        CheckConstraint("reward_amount > 0", name="reward_positive"),
        CheckConstraint("positions_available >= 1 AND positions_available <= 100", name="positions_range"),
        CheckConstraint(
            "review_window_seconds IS NULL OR (review_window_seconds >= 60 AND review_window_seconds <= 2592000)",
            name="review_window_range",
        ),
        CheckConstraint(
            "application_deadline IS NULL OR completion_deadline IS NULL "
            "OR application_deadline <= completion_deadline",
            name="deadline_order",
        ),
        Index("ix_bounties_search_vector", "search_vector", postgresql_using="gin"),
        Index("ix_bounties_status_published", "status", "published_at"),
        Index("ix_bounties_requester_status", "requester_id", "status"),
        # Marketplace default sort: newest by coalesce(published_at, created_at).
        Index("ix_bounties_listed_at", func.coalesce(text("published_at"), text("created_at")).desc()),
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    short_description: Mapped[str] = mapped_column(String(280), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Category] = mapped_column(
        str_enum(Category, "bounty_category"), nullable=False, index=True
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        str_enum(Difficulty, "bounty_difficulty"), nullable=False, index=True
    )
    reward_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    # Asset code for display ("XLM", "USDC"); reward_asset_identifier below is the authoritative value.
    reward_asset: Mapped[str] = mapped_column(String(64), nullable=False, default="XLM")
    # The reward asset: "native" (XLM) or "CODE:ISSUER", an entry of the reward asset registry (app.modules.assets).
    reward_asset_identifier: Mapped[str] = mapped_column(
        String(80), nullable=False, default="native", server_default="native", index=True
    )
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[BountyStatus] = mapped_column(
        str_enum(BountyStatus, "bounty_status"), nullable=False, default=BountyStatus.DRAFT, index=True
    )
    application_deadline: Mapped[datetime | None]
    completion_deadline: Mapped[datetime | None]
    positions_available: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Escrow v2: seconds the requester has to answer work recorded on-chain (None = the platform default).
    review_window_seconds: Mapped[int | None] = mapped_column(Integer)
    eligibility_criteria: Mapped[str | None] = mapped_column(Text)
    submission_requirements: Mapped[str | None] = mapped_column(Text)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text)
    repository_url: Mapped[str | None] = mapped_column(String(500))
    # Approval needs a merged pull request, verified through GitHub, from the contributor (modules/github).
    require_merged_pr: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    visibility: Mapped[Visibility] = mapped_column(
        str_enum(Visibility, "bounty_visibility"), nullable=False, default=Visibility.PUBLIC
    )
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    applications_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    bookmarks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Free-form structured data: {"links": [{"label", "url"}], "cancel_reason": ..., "status_before_dispute": ...}
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    published_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(short_description, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'C')",
            persisted=True,
        ),
        deferred=True,
    )

    __mapper_args__ = {"version_id_col": version_id}

    requester: Mapped[User] = relationship(lazy="joined", innerjoin=True)
    tags: Mapped[list[BountyTag]] = relationship(
        back_populates="bounty", cascade="all, delete-orphan", lazy="selectin", order_by="BountyTag.tag"
    )
    skills: Mapped[list[BountySkill]] = relationship(
        back_populates="bounty",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BountySkill.skill_name",
    )

    @property
    def tag_names(self) -> list[str]:
        return [t.tag for t in self.tags]

    @property
    def skill_names(self) -> list[str]:
        return [s.skill_name for s in self.skills]

    @property
    def total_reward(self) -> Decimal:
        return self.reward_amount * self.positions_available


class BountyTag(UUIDPrimaryKey, Base):
    __tablename__ = "bounty_tags"
    __table_args__ = (
        UniqueConstraint("bounty_id", "tag"),
        # Recommendations match on the normalised name, which the plain index cannot serve.
        Index("ix_bounty_tags_normalized", text(r"regexp_replace(lower(btrim(tag)), '[\s_-]+', ' ', 'g')")),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    bounty: Mapped[Bounty] = relationship(back_populates="tags")


class BountySkill(UUIDPrimaryKey, Base):
    __tablename__ = "bounty_skills"
    __table_args__ = (
        UniqueConstraint("bounty_id", "skill_name"),
        # Recommendations match on the normalised name, which the plain index cannot serve.
        Index(
            "ix_bounty_skills_normalized",
            text(r"regexp_replace(lower(btrim(skill_name)), '[\s_-]+', ' ', 'g')"),
        ),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), index=True)
    skill_name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    bounty: Mapped[Bounty] = relationship(back_populates="skills")


class BountyBookmark(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bounty_bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "bounty_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), index=True)


class BountyViewDaily(Base):
    """Daily unique-ish view counter (deduplicated per viewer per day in Redis) for the popularity metric."""

    __tablename__ = "bounty_view_daily"

    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bounties.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
