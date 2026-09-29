"""Reward asset registry, trustline status, and asset operation schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from app.core.schemas import APIModel, Asset, Money, OptionalMoney, UserSummary
from app.modules.assets.models import AssetOperationKind, AssetOperationStatus, ContractStatus


class TrustlineState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"  # XLM, a contract (C…) address, or the asset's own issuer
    ACTIVE = "ACTIVE"  # the account has an authorized trustline
    MISSING = "MISSING"  # no trustline: a SAC transfer to this G-address would fail
    UNAUTHORIZED = "UNAUTHORIZED"  # a trustline exists but the issuer has not authorized it
    ACCOUNT_MISSING = "ACCOUNT_MISSING"  # the account does not exist on the network yet
    NO_WALLET = "NO_WALLET"  # the user has no verified wallet on this network
    UNKNOWN = "UNKNOWN"  # Horizon could not be reached; nothing is blocked on an unknown state

    @property
    def can_receive(self) -> bool:
        return self in (TrustlineState.NOT_REQUIRED, TrustlineState.ACTIVE, TrustlineState.UNKNOWN)


class RewardAssetOut(APIModel):
    id: uuid.UUID
    asset: Asset
    name: str
    is_default: bool
    requires_trustline: bool  # classic assets need a trustline on G-addresses before they can be received
    faucet_url: str | None = None  # where to get test units (Circle's faucet for Testnet USDC)


class AdminRewardAssetOut(RewardAssetOut):
    is_enabled: bool
    contract_status: ContractStatus
    symbol: str | None
    decimals: int
    issuer_flags: dict[str, bool]
    sort_order: int
    bounty_count: int
    verified_at: datetime | None
    created_by: UserSummary | None
    created_at: datetime
    updated_at: datetime


class AssetCreate(APIModel):
    """A classic asset by code and issuer, or a Stellar Asset Contract by its contract id."""

    code: str | None = Field(default=None, max_length=12)
    issuer: str | None = Field(default=None, max_length=56)
    contract_id: str | None = Field(default=None, max_length=56)
    name: str | None = Field(default=None, max_length=80)
    enable: bool = True

    @field_validator("code", "issuer", "contract_id", "name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def _one_form(self) -> AssetCreate:
        if self.contract_id:
            if self.code or self.issuer:
                raise ValueError("Give either a contract id, or an asset code and issuer, not both.")
        elif not (self.code and self.issuer):
            raise ValueError("Give an asset code and issuer, or a Stellar Asset Contract id.")
        return self


class AssetUpdate(APIModel):
    is_enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class TrustlineStatus(APIModel):
    asset: Asset
    address: str | None
    state: TrustlineState
    balance: OptionalMoney = None


class WalletAssets(APIModel):
    wallet_id: uuid.UUID
    address: str
    network: str
    account_exists: bool | None  # None: Horizon could not be reached
    native_balance: OptionalMoney = None
    native_spendable: OptionalMoney = None  # after the account's reserve and open offers
    trustlines: list[TrustlineStatus]


class ApplicantTrustline(APIModel):
    contributor_id: uuid.UUID
    address: str | None
    state: TrustlineState


class BountyTrustlines(APIModel):
    asset: Asset
    requires_trustline: bool
    applicants: list[ApplicantTrustline]


class FundingReadiness(APIModel):
    asset: Asset
    address: str
    required: Money  # what the next deposit needs (the remaining escrow amount)
    available: OptionalMoney  # spendable balance of the asset in this wallet
    trustline: TrustlineState
    ready: bool
    message: str | None = None
    faucet_url: str | None = None


class AssetOperationOut(APIModel):
    id: uuid.UUID
    kind: AssetOperationKind
    status: AssetOperationStatus
    asset: Asset
    network: str
    source_address: str
    transaction_hash: str
    ledger_sequence: int | None
    submitted_at: datetime | None
    confirmed_at: datetime | None
    failure_reason: str | None
    explorer_url: str | None
    created_at: datetime


class PreparedAssetOperation(APIModel):
    operation: AssetOperationOut
    unsigned_xdr: str
    network_passphrase: str
    network: str
    description: str
    fee_estimate_stroops: str | None
    expires_at: datetime


class WalletRequest(APIModel):
    wallet_address: str = Field(min_length=56, max_length=56)


class OperationSubmit(APIModel):
    signed_xdr: str = Field(min_length=1, max_length=100_000)
