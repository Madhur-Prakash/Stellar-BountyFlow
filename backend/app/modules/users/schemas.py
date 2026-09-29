"""User, profile, wallet, and statistics schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, computed_field, field_validator

from app.core.schemas import APIModel, AssetAmount, Money, UrlStr
from app.modules.users.models import Role

USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,30}$")
RESERVED_USERNAMES = {"admin", "root", "support", "bountyflow", "api", "app", "me", "moderator", "system"}


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("Username must be 3–30 characters: lowercase letters, numbers, '_' or '-'")
    if value in RESERVED_USERNAMES:
        raise ValueError("This username is reserved")
    return value


def normalize_tags(values: list[str], *, max_items: int = 15, max_len: int = 40) -> list[str]:
    seen: dict[str, None] = {}
    for raw in values:
        cleaned = re.sub(r"\s+", " ", raw.strip())[:max_len]
        if cleaned:
            seen.setdefault(cleaned.lower() if cleaned.isascii() else cleaned, None)
    result = list(seen)
    if len(result) > max_items:
        raise ValueError(f"At most {max_items} items are allowed")
    return result


class Onboarding(APIModel):
    email_verified: bool
    profile_completed: bool
    role_selected: bool
    wallet_connected: bool
    first_action_taken: bool
    completed: bool


class Me(APIModel):
    id: uuid.UUID
    email: str
    email_verified: bool
    username: str
    display_name: str
    avatar_url: str | None
    bio: str | None
    role: Role
    permissions: list[str]
    skills: list[str]
    interests: list[str]
    github_url: str | None
    portfolio_url: str | None
    wants_to_request: bool
    wants_to_contribute: bool
    onboarding: Onboarding
    created_at: datetime


class ProfileUpdate(APIModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    username: str | None = None
    avatar_url: UrlStr | None = None
    bio: str | None = Field(default=None, max_length=1000)
    skills: list[str] | None = None
    interests: list[str] | None = None
    github_url: UrlStr | None = None
    portfolio_url: UrlStr | None = None
    wants_to_request: bool | None = None
    wants_to_contribute: bool | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        return normalize_username(v) if v is not None else None

    @field_validator("skills", "interests")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return normalize_tags(v, max_items=20) if v is not None else None

    @field_validator("github_url")
    @classmethod
    def _github(cls, v: str | None) -> str | None:
        if v and not re.match(r"^https://(www\.)?github\.com/", str(v)):
            raise ValueError("GitHub URL must start with https://github.com/")
        return v

    @field_validator("display_name", "bio")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None


class WalletOut(APIModel):
    id: uuid.UUID
    public_address: str
    network: str
    verification_status: str
    verified_at: datetime
    created_at: datetime
    # The wallet app the ownership proof was signed with, and how: sep10, sep53 or sep45.
    wallet_app: str | None = None
    proof_method: str | None = None
    is_primary: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def kind(self) -> Literal["account", "contract"]:
        return "contract" if self.public_address.startswith("C") else "account"


class PublicWallet(APIModel):
    public_address: str
    network: str
    verified_at: datetime


class UserStats(APIModel):
    bounties_created: int
    bounties_completed_as_requester: int
    contributions_completed: int
    applications_submitted: int
    acceptance_rate: float | None
    approval_rate: float | None
    total_rewards_received: Money  # XLM payouts confirmed on-chain
    total_rewards_paid: Money  # XLM
    # Every asset, never added across assets (XLM, USDC, ...).
    rewards_received_by_asset: list[AssetAmount] = []
    rewards_paid_by_asset: list[AssetAmount] = []


class PublicProfile(APIModel):
    id: uuid.UUID
    username: str
    display_name: str
    avatar_url: str | None
    bio: str | None
    skills: list[str]
    interests: list[str]
    github_url: str | None
    portfolio_url: str | None
    joined_at: datetime
    wallets: list[PublicWallet]
    stats: UserStats


# Wallet apps a proof may be recorded for (the frontend's wallet ids; "passkey" is a BountyFlow smart wallet).
WALLET_APP_RE = r"^[a-z0-9][a-z0-9_.-]{1,31}$"


class WalletChallengeRequest(APIModel):
    public_address: str = Field(min_length=56, max_length=56)
    # sep10: sign a challenge transaction (default for G... addresses); sep53: sign a message;
    # sep45: authorize a contract call (contract accounts, C..., the default for them).
    method: Literal["sep10", "sep53", "sep45"] | None = None


class WalletChallengeResponse(APIModel):
    method: Literal["sep10", "sep53", "sep45"] = "sep10"
    challenge_xdr: str | None = None
    message: str | None = None
    authorization_entries: str | None = None
    network_passphrase: str
    expires_at: datetime


class WalletVerifyRequest(APIModel):
    public_address: str = Field(min_length=56, max_length=56)
    signed_challenge_xdr: str | None = Field(default=None, min_length=1, max_length=20_000)
    signed_message: str | None = Field(default=None, min_length=1, max_length=200)
    signed_authorization_entries: str | None = Field(default=None, min_length=1, max_length=20_000)
    wallet_app: str | None = Field(default=None, pattern=WALLET_APP_RE)
