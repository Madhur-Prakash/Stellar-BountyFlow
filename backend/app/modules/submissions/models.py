"""Work submissions, with an append-only revision history."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.bounties.models import Bounty
from app.modules.users.models import User


class SubmissionStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    RESUBMITTED = "RESUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BountySubmission(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "bounty_submissions"

    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), index=True)
    contributor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bounty_assignments.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(String(500))
    evidence_links: Mapped[list[str]] = mapped_column(ARRAY(String(500)), nullable=False, server_default="{}")
    status: Mapped[SubmissionStatus] = mapped_column(
        str_enum(SubmissionStatus, "submission_status"), nullable=False, default=SubmissionStatus.SUBMITTED
    )
    review_feedback: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None]

    bounty: Mapped[Bounty] = relationship(lazy="joined", innerjoin=True)
    contributor: Mapped[User] = relationship(foreign_keys=[contributor_id], lazy="joined", innerjoin=True)
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id], lazy="joined")


class SubmissionRevision(UUIDPrimaryKey, CreatedAt, Base):
    """Immutable snapshot of each submitted version."""

    __tablename__ = "submission_revisions"
    __table_args__ = (UniqueConstraint("submission_id", "version"),)

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bounty_submissions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(String(500))
    evidence_links: Mapped[list[str]] = mapped_column(ARRAY(String(500)), nullable=False, server_default="{}")
