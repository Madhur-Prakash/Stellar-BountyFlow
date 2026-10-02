"""Product feedback sent from the floating form on the public site and in the workspace.

One row per note. Signed-in senders are recorded through ``user_id``; a signed-out sender may leave an address
in ``email`` so the maintainer can write back. Nothing else about the sender is stored: no IP address (the
rate limiter keeps one in Redis for an hour and never writes it here), no wallet address, no token.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.users.models import User


class FeedbackKind(StrEnum):
    BUG = "BUG"
    IDEA = "IDEA"
    PRAISE = "PRAISE"
    OTHER = "OTHER"


class FeedbackStatus(StrEnum):
    NEW = "NEW"
    HANDLED = "HANDLED"


class Feedback(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_feedback"
    __table_args__ = (
        # The queue is always newest first: unfiltered, by status, and by kind.
        Index("ix_bountyflow_feedback_created", "created_at"),
        Index("ix_bountyflow_feedback_status_created", "status", "created_at"),
        Index("ix_bountyflow_feedback_kind_created", "kind", "created_at"),
    )

    # SET NULL rather than CASCADE: a closed account's note stays readable, without its author.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="SET NULL"), index=True
    )
    # Only ever filled for a signed-out sender who chose to leave one.
    email: Mapped[str | None] = mapped_column(String(320))
    kind: Mapped[FeedbackKind] = mapped_column(str_enum(FeedbackKind, "feedback_kind"), nullable=False)
    status: Mapped[FeedbackStatus] = mapped_column(
        str_enum(FeedbackStatus, "feedback_status"), nullable=False, default=FeedbackStatus.NEW
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Captured context, declared in the form: the route the sender was on and the size of their window.
    path: Mapped[str | None] = mapped_column(String(200))
    viewport_width: Mapped[int | None] = mapped_column(Integer)
    viewport_height: Mapped[int | None] = mapped_column(Integer)
    # Read from the request header, never from the page.
    user_agent: Mapped[str | None] = mapped_column(String(400))

    handled_at: Mapped[datetime | None]
    handled_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="SET NULL")
    )
    handled_note: Mapped[str | None] = mapped_column(Text)

    sender: Mapped[User | None] = relationship(foreign_keys=[user_id], lazy="joined")
    handled_by: Mapped[User | None] = relationship(foreign_keys=[handled_by_id], lazy="joined")

    @property
    def is_handled(self) -> bool:
        return self.status is FeedbackStatus.HANDLED
