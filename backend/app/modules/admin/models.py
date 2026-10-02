"""Moderation reports and the immutable audit log."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.users.models import User


class ReportStatus(StrEnum):
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    ACTIONED = "ACTIONED"
    DISMISSED = "DISMISSED"


class ReportTarget(StrEnum):
    BOUNTY = "BOUNTY"
    USER = "USER"
    SUBMISSION = "SUBMISSION"
    QA_POST = "QA_POST"  # a bounty question or reply (modules/qa)


class UserReport(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_user_reports"
    __table_args__ = (Index("ix_bountyflow_user_reports_target", "target_type", "target_id"),)

    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="CASCADE"), index=True
    )
    target_type: Mapped[ReportTarget] = mapped_column(str_enum(ReportTarget, "report_target"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(
        str_enum(ReportStatus, "report_status"), nullable=False, default=ReportStatus.OPEN, index=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None]

    reporter: Mapped[User] = relationship(foreign_keys=[reporter_id], lazy="joined", innerjoin=True)


class AuditLog(UUIDPrimaryKey, CreatedAt, Base):
    """Append-only record of important state transitions. The application never updates or deletes rows."""

    __tablename__ = "bountyflow_audit_logs"
    __table_args__ = (
        Index("ix_bountyflow_audit_logs_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_bountyflow_audit_logs_bounty_created", "bounty_id", "created_at"),
        # The screening decision list and the export's audit section read only the screening actions.
        Index(
            "ix_bountyflow_audit_logs_screening",
            "action",
            "created_at",
            postgresql_where=text("action LIKE 'screening.%'"),
        ),
    )

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    bounty_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="SET NULL")
    )
    is_public: Mapped[bool] = mapped_column(nullable=False, default=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))

    actor: Mapped[User | None] = relationship(lazy="joined")
