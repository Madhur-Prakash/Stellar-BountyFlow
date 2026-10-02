"""Applications to bounties and the resulting contributor assignments."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.bounties.models import Bounty
from app.modules.users.models import User


class ApplicationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"  # contributor withdrew or was unassigned (e.g. dispute / cancellation)


class BountyApplication(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "bountyflow_bounty_applications"
    __table_args__ = (
        # At most one live application per contributor per bounty (enforced by the database).
        Index(
            "uq_bountyflow_applications_one_active",
            "bounty_id",
            "contributor_id",
            unique=True,
            postgresql_where="status IN ('PENDING', 'ACCEPTED')",
        ),
        Index("ix_bountyflow_applications_bounty_status", "bounty_id", "status"),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="CASCADE"), index=True
    )
    contributor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="CASCADE"), index=True
    )
    cover_message: Mapped[str] = mapped_column(Text, nullable=False)
    relevant_experience: Mapped[str | None] = mapped_column(Text)
    work_samples: Mapped[list[str]] = mapped_column(ARRAY(String(500)), nullable=False, server_default="{}")
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus, "application_status"), nullable=False, default=ApplicationStatus.PENDING
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]

    bounty: Mapped[Bounty] = relationship(lazy="joined", innerjoin=True)
    contributor: Mapped[User] = relationship(foreign_keys=[contributor_id], lazy="joined", innerjoin=True)


class BountyAssignment(UUIDPrimaryKey, Base):
    __tablename__ = "bountyflow_bounty_assignments"
    __table_args__ = (
        Index(
            "uq_bountyflow_assignments_one_live",
            "bounty_id",
            "contributor_id",
            unique=True,
            postgresql_where="status IN ('ACTIVE', 'COMPLETED')",
        ),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="CASCADE"), index=True
    )
    contributor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounty_applications.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        str_enum(AssignmentStatus, "assignment_status"), nullable=False, default=AssignmentStatus.ACTIVE
    )
    # True once the `assign` contract call is confirmed on-chain (protects the contributor from refunds).
    onchain_assigned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    assigned_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None]
    released_at: Mapped[datetime | None]

    contributor: Mapped[User] = relationship(lazy="joined", innerjoin=True)
