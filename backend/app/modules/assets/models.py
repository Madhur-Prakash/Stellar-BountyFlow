"""Reward asset registry and the wallet-signed asset operations (trustlines, SAC deployments).

A bounty's reward asset must be an enabled registry entry on the active network. Entries are never deleted, only
disabled, so every stored asset identifier keeps resolving. Operation rows are kept like blockchain transactions:
failures keep their reason for auditability.
"""

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


class AssetKind(StrEnum):
    NATIVE = "NATIVE"  # XLM
    CLASSIC = "CLASSIC"  # a classic Stellar asset (CODE:ISSUER), moved through its Stellar Asset Contract


class ContractStatus(StrEnum):
    DEPLOYED = "DEPLOYED"  # the asset's SAC exists on the network and reports 7 decimals
    NOT_DEPLOYED = "NOT_DEPLOYED"  # nobody has deployed the SAC yet; an admin can deploy it


class AssetOperationKind(StrEnum):
    TRUSTLINE = "TRUSTLINE"  # changeTrust from a user's verified wallet
    DEPLOY_CONTRACT = "DEPLOY_CONTRACT"  # createStellarAssetContract from an admin's verified wallet


class AssetOperationStatus(StrEnum):
    SIGNATURE_REQUIRED = "SIGNATURE_REQUIRED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"  # the transaction succeeded AND its effect was read back from the network
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class RewardAsset(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "bountyflow_reward_assets"
    __table_args__ = (
        UniqueConstraint("network", "identifier", name="uq_bountyflow_reward_assets_network_identifier"),
        UniqueConstraint("network", "contract_id", name="uq_bountyflow_reward_assets_network_contract"),
        Index("ix_bountyflow_reward_assets_network_enabled", "network", "is_enabled"),
    )

    network: Mapped[str] = mapped_column(String(16), nullable=False)
    identifier: Mapped[str] = mapped_column(String(80), nullable=False)  # "native" or CODE:ISSUER
    kind: Mapped[AssetKind] = mapped_column(str_enum(AssetKind, "reward_asset_kind"), nullable=False)
    code: Mapped[str] = mapped_column(String(12), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(56))
    contract_id: Mapped[str] = mapped_column(String(56), nullable=False)  # derived SAC address
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32))  # as reported by the contract
    decimals: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    contract_status: Mapped[ContractStatus] = mapped_column(
        str_enum(ContractStatus, "reward_asset_contract_status"), nullable=False
    )
    # Issuer account flags read from Horizon (auth_required, auth_revocable, auth_clawback_enabled, ...).
    issuer_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    verified_at: Mapped[datetime | None]
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="SET NULL")
    )


class AssetOperation(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_asset_operations"
    __table_args__ = (
        UniqueConstraint("network", "transaction_hash", name="uq_bountyflow_asset_operations_network_hash"),
        Index("ix_bountyflow_asset_operations_user_created", "user_id", "created_at"),
        Index("ix_bountyflow_asset_operations_status", "status"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bountyflow_users.id", ondelete="SET NULL"))
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_reward_assets.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[AssetOperationKind] = mapped_column(
        str_enum(AssetOperationKind, "asset_operation_kind"), nullable=False
    )
    status: Mapped[AssetOperationStatus] = mapped_column(
        str_enum(AssetOperationStatus, "asset_operation_status"), nullable=False
    )
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    source_address: Mapped[str] = mapped_column(String(56), nullable=False)
    transaction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    unsigned_xdr: Mapped[str | None] = mapped_column(Text)
    # The exact envelope handed to the network (the signed transaction, or the sponsor's fee bump around it).
    # Kept so a retry after a lost response re-sends identical bytes instead of a second transaction.
    submitted_xdr: Mapped[str | None] = mapped_column(Text)
    # The sponsored_transactions row when the platform paid this operation's network fee.
    sponsorship_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_sponsored_transactions.id", ondelete="SET NULL")
    )
    fee_stroops: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None]
    submitted_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]
    ledger_sequence: Mapped[int | None] = mapped_column(Integer)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    result_code: Mapped[str | None] = mapped_column(String(40))
