"""Saved searches, the bounties they matched, and the persisted skill graph."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum


class AlertFrequency(StrEnum):
    INSTANT = "INSTANT"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    OFF = "OFF"


DIGEST_FREQUENCIES = frozenset({AlertFrequency.DAILY, AlertFrequency.WEEKLY})


class MatchDelivery(StrEnum):
    PENDING = "PENDING"  # waiting for the search's next digest
    ALERTED = "ALERTED"  # sent as an instant alert
    DIGESTED = "DIGESTED"  # included in a digest
    SKIPPED = "SKIPPED"  # alerts were off or paused, or the bounty stopped matching before its digest


class SavedSearch(UUIDPrimaryKey, Timestamps, Base):
    """A marketplace query (text, every filter and the sort) a user keeps, with its alert settings."""

    __tablename__ = "bountyflow_saved_searches"
    __table_args__ = (Index("ix_bountyflow_saved_searches_digest_due", "alert_frequency", "next_digest_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # SavedSearchFilters: the marketplace filters, with the deadline kept as a rolling window.
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    alert_frequency: Mapped[AlertFrequency] = mapped_column(
        str_enum(AlertFrequency, "saved_search_alert_frequency"),
        nullable=False,
        default=AlertFrequency.INSTANT,
    )
    notify_in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_viewed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    next_digest_at: Mapped[datetime | None]
    last_digest_at: Mapped[datetime | None]

    @property
    def alerts_active(self) -> bool:
        return not self.is_paused and self.alert_frequency != AlertFrequency.OFF


class SavedSearchMatch(Base):
    """One bounty that matched one saved search. The primary key deduplicates alerts per (search, bounty)."""

    __tablename__ = "bountyflow_saved_search_matches"
    __table_args__ = (
        Index("ix_bountyflow_saved_search_matches_search_matched", "saved_search_id", "matched_at"),
        # The digest job only ever reads the matches it has not delivered yet.
        Index(
            "ix_bountyflow_saved_search_matches_pending",
            "saved_search_id",
            "matched_at",
            postgresql_where=text("delivery = 'PENDING'"),
        ),
    )

    saved_search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_saved_searches.id", ondelete="CASCADE"), primary_key=True
    )
    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    matched_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    trigger_event: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_id: Mapped[uuid.UUID | None]
    delivery: Mapped[MatchDelivery] = mapped_column(
        str_enum(MatchDelivery, "saved_search_match_delivery"), nullable=False, default=MatchDelivery.PENDING
    )
    delivered_at: Mapped[datetime | None]


class SkillNode(Base):
    """A normalised skill in the graph: how many documents (bounties, profiles) carry it, and its raw spellings."""

    __tablename__ = "bountyflow_skill_nodes"

    skill: Mapped[str] = mapped_column(String(40), primary_key=True)
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Raw names as written on bounties (required skills), most used first: the marketplace filters on these.
    bounty_forms: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, server_default="{}")
    computed_at: Mapped[datetime] = mapped_column(nullable=False)


class SkillEdge(Base):
    """A weighted co-occurrence edge, stored in both directions so neighbours are one indexed lookup."""

    __tablename__ = "bountyflow_skill_edges"

    skill: Mapped[str] = mapped_column(String(40), primary_key=True)
    related: Mapped[str] = mapped_column(String(40), primary_key=True)
    co_count: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(nullable=False)
