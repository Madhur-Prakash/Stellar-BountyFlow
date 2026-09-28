"""Disputes and their evidence."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.bounties.models import Bounty
from app.modules.users.models import User


class DisputeStatus(StrEnum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class DisputeResolution(StrEnum):
    RELEASE_TO_CONTRIBUTOR = "RELEASE_TO_CONTRIBUTOR"
    REFUND_TO_REQUESTER = "REFUND_TO_REQUESTER"
    DISMISSED = "DISMISSED"


class Dispute(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "disputes"
    __table_args__ = (
        Index(
            "uq_disputes_one_open_per_bounty",
            "bounty_id",
            unique=True,
            postgresql_where="status IN ('OPEN', 'UNDER_REVIEW')",
        ),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), index=True)
    raised_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The assigned contributor the dispute concerns (needed for any on-chain resolution).
    contributor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DisputeStatus] = mapped_column(
        str_enum(DisputeStatus, "dispute_status"), nullable=False, default=DisputeStatus.OPEN
    )
    assigned_moderator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution: Mapped[DisputeResolution | None] = mapped_column(
        str_enum(DisputeResolution, "dispute_resolution")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None]
    status_before: Mapped[str | None] = mapped_column(String(32))

    bounty: Mapped[Bounty] = relationship(lazy="joined", innerjoin=True)
    raised_by: Mapped[User] = relationship(foreign_keys=[raised_by_id], lazy="joined", innerjoin=True)
    assigned_moderator: Mapped[User | None] = relationship(
        foreign_keys=[assigned_moderator_id], lazy="joined"
    )
    evidence: Mapped[list[DisputeEvidence]] = relationship(
        back_populates="dispute", lazy="selectin", order_by="DisputeEvidence.created_at"
    )


class DisputeEvidence(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "dispute_evidence"

    dispute_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disputes.id", ondelete="CASCADE"), index=True)
    submitted_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(String(500))

    dispute: Mapped[Dispute] = relationship(back_populates="evidence")
    submitted_by: Mapped[User] = relationship(lazy="joined", innerjoin=True)
