"""Passkey wallet, wallet options and fee sponsorship schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.core.schemas import APIModel, OptionalMoney, UserSummary
from app.modules.wallets.models import PasskeyWalletStatus, SponsorshipKind, SponsorshipStatus


class SponsorshipOptions(APIModel):
    enabled: bool
    sponsor_address: str | None
    # Contributor-side contract functions whose network fee BountyFlow pays.
    functions: list[str]
    daily_tx_limit: int
    used_today: int


class PasskeyOptions(APIModel):
    enabled: bool
    # Why passkey wallets are unavailable, when they are (for example no sponsor key configured).
    unavailable_reason: str | None
    wasm_hash: str
    rpc_url: str
    network_passphrase: str


class WalletOptions(APIModel):
    sponsorship: SponsorshipOptions
    passkey: PasskeyOptions


class PasskeyWalletCreate(APIModel):
    key_id: str = Field(min_length=8, max_length=1400, pattern=r"^[A-Za-z0-9_-]+$")
    public_key: str = Field(min_length=64, max_length=130)
    deploy_xdr: str = Field(min_length=1, max_length=20_000)


class PasskeyWalletOut(APIModel):
    id: uuid.UUID
    contract_id: str
    key_id: str
    public_key: str
    network: str
    status: PasskeyWalletStatus
    wasm_hash: str
    deploy_tx_hash: str | None
    creation_ledger: int | None
    deployed_at: datetime | None
    failure_reason: str | None
    explorer_url: str | None
    # The address is linked as a verified wallet (SEP-45 proof done).
    linked: bool
    created_at: datetime


class WalletCandidateOut(APIModel):
    """passkey-kit's ``WalletCandidateLookup`` (schema 2) for connecting a wallet on a new device."""

    lookup_schema: int = Field(2, serialization_alias="schema")
    complete: bool
    indexed_through_ledger: int = Field(serialization_alias="indexedThroughLedger")
    candidates: list[dict[str, object]]


class SponsoredTransactionOut(APIModel):
    id: uuid.UUID
    kind: SponsorshipKind
    purpose: str
    status: SponsorshipStatus
    user: UserSummary | None
    source_address: str | None
    envelope_hash: str
    inner_hash: str | None
    contract_id: str | None
    function_name: str | None
    max_fee: OptionalMoney
    fee_charged: OptionalMoney
    ledger_sequence: int | None
    failure_reason: str | None
    explorer_url: str | None
    created_at: datetime
    confirmed_at: datetime | None


class SponsorshipOverview(APIModel):
    enabled: bool
    sponsor_address: str | None
    balance: OptionalMoney
    low_balance: bool
    stopped: bool
    low_balance_threshold: OptionalMoney
    stop_threshold: OptionalMoney
    max_fee: OptionalMoney
    daily_tx_limit: int
    daily_fee_limit: OptionalMoney
    sponsored_today: int
    fees_today: OptionalMoney
    recent: list[SponsoredTransactionOut]
