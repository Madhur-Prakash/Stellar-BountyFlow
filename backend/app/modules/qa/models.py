"""Bounty Q&A: public questions with one level of replies, upvotes, and moderation state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.modules.users.models import User


class BountyQAPost(UUIDPrimaryKey, Timestamps, Base):
    """A question (``parent_id`` is NULL) or a reply to one. Replies never have replies of their own.

    Posts are soft-deleted (``deleted_at``, body cleared) so a thread keeps its shape, and moderators hide
    them (``hidden_at``) without destroying the evidence a report points at."""

    __tablename__ = "bounty_qa_posts"
    __table_args__ = (
        Index("ix_bounty_qa_posts_bounty_thread", "bounty_id", "parent_id", "created_at"),
        # The data export and the anonymiser both walk one author's posts oldest first.
        Index("ix_bounty_qa_posts_author_created", "author_id", "created_at"),
        # Counting the questions shown on a bounty card or its detail page.
        Index(
            "ix_bounty_qa_posts_visible_questions",
            "bounty_id",
            postgresql_where=text("parent_id IS NULL AND deleted_at IS NULL AND hidden_at IS NULL"),
        ),
        # At most one accepted reply per question.
        Index(
            "uq_bounty_qa_posts_accepted_reply",
            "parent_id",
            unique=True,
            postgresql_where=text("is_accepted"),
        ),
        CheckConstraint("parent_id IS NULL OR NOT is_pinned", name="replies_not_pinned"),
        CheckConstraint("parent_id IS NOT NULL OR NOT is_accepted", name="questions_not_accepted"),
        CheckConstraint("upvotes_count >= 0", name="upvotes_non_negative"),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bounty_qa_posts.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    upvotes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    edited_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    hidden_at: Mapped[datetime | None]
    hidden_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    hidden_reason: Mapped[str | None] = mapped_column(Text)

    author: Mapped[User] = relationship(foreign_keys=[author_id], lazy="joined", innerjoin=True)

    @property
    def is_question(self) -> bool:
        return self.parent_id is None

    @property
    def is_visible(self) -> bool:
        return self.deleted_at is None and self.hidden_at is None


class BountyQAVote(CreatedAt, Base):
    """One upvote per user per post ("most helpful" sort)."""

    __tablename__ = "bounty_qa_votes"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bounty_qa_posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
