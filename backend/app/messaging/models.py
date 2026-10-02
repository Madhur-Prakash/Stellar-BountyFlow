"""Transactional outbox and consumer idempotency tables."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey


class OutboxEvent(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_outbox_events"
    __table_args__ = (
        Index(
            "ix_bountyflow_outbox_unpublished", "created_at", postgresql_where=text("published_at IS NULL")
        ),
    )

    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # the full event envelope
    published_at: Mapped[datetime | None]
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedEvent(CreatedAt, Base):
    """Records (consumer, event_id) pairs so redelivered Kafka messages are processed at most once."""

    __tablename__ = "bountyflow_processed_events"

    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
