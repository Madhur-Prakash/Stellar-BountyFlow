"""User identity, profile, skills, and verified wallets."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum


class Role(StrEnum):
    USER = "USER"
    MODERATOR = "MODERATOR"
    ADMIN = "ADMIN"


class WalletVerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "bountyflow_users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified_at: Mapped[datetime | None]
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    username: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    bio: Mapped[str | None] = mapped_column(String(1000))
    github_url: Mapped[str | None] = mapped_column(String(300))
    portfolio_url: Mapped[str | None] = mapped_column(String(300))
    interests: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, server_default="{}")
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"), nullable=False, default=Role.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    wants_to_request: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    wants_to_contribute: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    onboarding_completed_at: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]

    skills: Mapped[list[UserSkill]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin", order_by="UserSkill.skill_name"
    )
    wallets: Mapped[list[Wallet]] = relationship(back_populates="user", lazy="raise")

    @property
    def skill_names(self) -> list[str]:
        return [s.skill_name for s in self.skills]

    @property
    def is_moderator(self) -> bool:
        return self.role in (Role.MODERATOR, Role.ADMIN)


class UserSkill(UUIDPrimaryKey, Base):
    __tablename__ = "bountyflow_user_skills"
    __table_args__ = (
        UniqueConstraint("user_id", "skill_name"),
        # Recommendations match on the normalised name, which the plain index cannot serve.
        Index(
            "ix_bountyflow_user_skills_normalized",
            text(r"regexp_replace(lower(btrim(skill_name)), '[\s_-]+', ' ', 'g')"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="CASCADE"), index=True
    )
    skill_name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    user: Mapped[User] = relationship(back_populates="skills")


class Wallet(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_wallets"
    __table_args__ = (
        # One verified owner per address per network; the same user can't add an address twice.
        Index(
            "uq_bountyflow_wallets_active_address_network",
            "public_address",
            "network",
            unique=True,
            postgresql_where="verification_status = 'VERIFIED'",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="CASCADE"), index=True
    )
    public_address: Mapped[str] = mapped_column(String(56), nullable=False, index=True)
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    verification_status: Mapped[WalletVerificationStatus] = mapped_column(
        str_enum(WalletVerificationStatus, "wallet_verification_status"),
        nullable=False,
        default=WalletVerificationStatus.VERIFIED,
    )
    verified_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]
    verification_note: Mapped[str | None] = mapped_column(Text)
    # The wallet app the ownership proof was signed with (freighter, xbull, albedo, lobstr, hana, passkey, ...)
    # and the proof itself: sep10 (challenge transaction), sep53 (signed message) or sep45 (contract account).
    wallet_app: Mapped[str | None] = mapped_column(String(32))
    proof_method: Mapped[str | None] = mapped_column(String(16))
    # The wallet payouts go to when a user has several; otherwise the most recently verified one.
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    user: Mapped[User] = relationship(back_populates="wallets")
