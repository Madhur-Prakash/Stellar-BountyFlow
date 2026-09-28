"""Sessions and single-use tokens for email verification and password reset."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey


class UserSession(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # The hash of the refresh token that was rotated away. Presenting it again signals token theft.
    previous_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(String(64))
    last_used_at: Mapped[datetime | None]
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_address: Mapped[str | None] = mapped_column(String(64))


class EmailVerificationToken(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None]


class PasswordResetToken(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None]
