"""In-app notifications, per-user preferences, and the email delivery log."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum


class NotificationType(StrEnum):
    BOUNTY_PUBLISHED = "BOUNTY_PUBLISHED"
    BOUNTY_FUNDED = "BOUNTY_FUNDED"
    APPLICATION_RECEIVED = "APPLICATION_RECEIVED"
    APPLICATION_ACCEPTED = "APPLICATION_ACCEPTED"
    APPLICATION_REJECTED = "APPLICATION_REJECTED"
    SUBMISSION_RECEIVED = "SUBMISSION_RECEIVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    SUBMISSION_APPROVED = "SUBMISSION_APPROVED"
    SUBMISSION_REJECTED = "SUBMISSION_REJECTED"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    BOUNTY_CANCELLED = "BOUNTY_CANCELLED"
    BOUNTY_EXPIRED = "BOUNTY_EXPIRED"
    DISPUTE_UPDATE = "DISPUTE_UPDATE"
    SYSTEM = "SYSTEM"


class EmailStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class Notification(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        # Idempotency: a domain event produces at most one notification per recipient.
        UniqueConstraint("user_id", "source_event_id", name="uq_notifications_user_event"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notification_type: Mapped[NotificationType] = mapped_column(
        str_enum(NotificationType, "notification_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(String(300))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_event_id: Mapped[uuid.UUID | None]
    read_at: Mapped[datetime | None]


class NotificationPreference(Timestamps, Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # {"APPLICATION_RECEIVED": {"in_app": true, "email": false}, ...}; missing keys use defaults.
    types: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EmailDelivery(UUIDPrimaryKey, CreatedAt, Base):
    """Outgoing email log. Bodies are rendered at send time; secrets (tokens) are never persisted here."""

    __tablename__ = "email_deliveries"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_email_deliveries_idempotency"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    to_address: Mapped[str] = mapped_column(String(320), nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[EmailStatus] = mapped_column(str_enum(EmailStatus, "email_status"), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None]
