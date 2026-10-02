"""Passkey smart wallets and the log of fee-sponsored transactions.

Linked wallets themselves (any kind, verified by signature) stay in ``users.models.Wallet``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum


class PasskeyWalletStatus(StrEnum):
    DEPLOYING = "DEPLOYING"  # the relayed deployment was submitted, not confirmed yet
    ACTIVE = "ACTIVE"  # the contract exists on-chain with the expected code and passkey signer
    FAILED = "FAILED"


class PasskeyWallet(UUIDPrimaryKey, Timestamps, Base):
    """A Soroban smart wallet (C...) whose signer is a WebAuthn secp256r1 passkey, deployed by BountyFlow's
    sponsor from the passkey-kit wallet WASM. Ownership is still proven separately (SEP-45) before the address
    is linked as a wallet."""

    __tablename__ = "bountyflow_passkey_wallets"
    __table_args__ = (
        UniqueConstraint("network", "contract_id", name="uq_bountyflow_passkey_wallets_network_contract"),
        UniqueConstraint("network", "key_id", name="uq_bountyflow_passkey_wallets_network_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="CASCADE"), index=True
    )
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(56), nullable=False)
    key_id: Mapped[str] = mapped_column(String(1400), nullable=False)  # base64url WebAuthn credential id
    public_key: Mapped[str] = mapped_column(String(130), nullable=False)  # hex, 65-byte uncompressed P-256
    wasm_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PasskeyWalletStatus] = mapped_column(
        str_enum(PasskeyWalletStatus, "passkey_wallet_status"),
        nullable=False,
        default=PasskeyWalletStatus.DEPLOYING,
    )
    deploy_tx_hash: Mapped[str | None] = mapped_column(String(64))
    creation_ledger: Mapped[int | None] = mapped_column(Integer)
    deployed_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(Text)


class SponsorshipKind(StrEnum):
    FEE_BUMP = "FEE_BUMP"  # a user-signed transaction wrapped in a FeeBumpTransaction paid by the sponsor
    RELAY = "RELAY"  # a smart-wallet invocation whose envelope the sponsor sources and signs


class SponsorshipStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class SponsoredTransaction(UUIDPrimaryKey, Timestamps, Base):
    """Every transaction whose network fee the platform sponsor paid (or bid to pay). Never deleted."""

    __tablename__ = "bountyflow_sponsored_transactions"
    __table_args__ = (
        UniqueConstraint(
            "network", "envelope_hash", name="uq_bountyflow_sponsored_transactions_network_envelope"
        ),
        Index("ix_bountyflow_sponsored_transactions_user_created", "user_id", "created_at"),
        Index("ix_bountyflow_sponsored_transactions_created", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bountyflow_users.id", ondelete="SET NULL"))
    blockchain_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_blockchain_transactions.id", ondelete="SET NULL"), index=True
    )
    passkey_wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_passkey_wallets.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[SponsorshipKind] = mapped_column(
        str_enum(SponsorshipKind, "sponsorship_kind"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)  # e.g. CONSENT_CANCEL, WALLET_DEPLOY
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    sponsor_address: Mapped[str] = mapped_column(String(56), nullable=False)
    source_address: Mapped[str | None] = mapped_column(String(56))  # the user's wallet (G... or C...)
    inner_hash: Mapped[str | None] = mapped_column(String(64))  # the user-signed transaction (fee bumps)
    envelope_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # what was sent to the network
    contract_id: Mapped[str | None] = mapped_column(String(56))
    function_name: Mapped[str | None] = mapped_column(String(64))
    max_fee_stroops: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_charged_stroops: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[SponsorshipStatus] = mapped_column(
        str_enum(SponsorshipStatus, "sponsorship_status"), nullable=False, default=SponsorshipStatus.SUBMITTED
    )
    ledger_sequence: Mapped[int | None] = mapped_column(Integer)
    confirmed_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
