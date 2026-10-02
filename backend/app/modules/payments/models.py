"""Escrows, blockchain transactions, and payment records.

Transaction rows are never deleted: failures are kept with their reason for auditability.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import MONEY, Base, CreatedAt, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.bounties.models import Bounty
from app.modules.users.models import User


class EscrowState(StrEnum):
    NOT_CREATED = "NOT_CREATED"
    AWAITING_FUNDING = "AWAITING_FUNDING"
    FUNDED = "FUNDED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    DISPUTED = "DISPUTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TxType(StrEnum):
    ESCROW_CREATE = "ESCROW_CREATE"
    ESCROW_FUND = "ESCROW_FUND"
    ASSIGN = "ASSIGN"
    PAYOUT = "PAYOUT"
    CANCEL_REQUEST = "CANCEL_REQUEST"
    CANCEL_CONSENT = "CANCEL_CONSENT"
    REFUND = "REFUND"
    DISPUTE_RAISE = "DISPUTE_RAISE"
    DISPUTE_RESOLVE = "DISPUTE_RESOLVE"
    WALLET_CHALLENGE = "WALLET_CHALLENGE"
    # Escrow v2
    MILESTONE_PAYOUT = "MILESTONE_PAYOUT"
    BATCH_PAYOUT = "BATCH_PAYOUT"
    SUBMIT_WORK = "SUBMIT_WORK"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT_SUBMISSION = "REJECT_SUBMISSION"
    CLAIM = "CLAIM"
    DISPUTE_VOTE = "DISPUTE_VOTE"


class TxStatus(StrEnum):
    CREATED = "CREATED"
    SIGNATURE_REQUIRED = "SIGNATURE_REQUIRED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class PaymentStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CREATED = "CREATED"
    SIGNATURE_REQUIRED = "SIGNATURE_REQUIRED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class BountyEscrow(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "bountyflow_bounty_escrows"
    __table_args__ = (
        CheckConstraint(
            "funded_amount >= 0 AND paid_out_amount >= 0 AND refunded_amount >= 0", name="amounts"
        ),
        CheckConstraint("paid_out_amount + refunded_amount <= funded_amount", name="conservation"),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="RESTRICT"), unique=True
    )
    contract_id: Mapped[str | None] = mapped_column(String(56))
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    onchain_bounty_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)  # hex BytesN<32>
    asset_identifier: Mapped[str] = mapped_column(String(80), nullable=False)  # "native" or CODE:ISSUER
    asset_contract_id: Mapped[str | None] = mapped_column(String(56))  # SAC contract address
    reward_per_position: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    positions: Mapped[int] = mapped_column(Integer, nullable=False)
    required_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    funded_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    paid_out_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    refunded_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal(0))
    requester_address: Mapped[str | None] = mapped_column(String(56))
    arbiter_address: Mapped[str | None] = mapped_column(String(56))
    onchain_deadline: Mapped[int | None] = mapped_column(Integer)
    state: Mapped[EscrowState] = mapped_column(
        str_enum(EscrowState, "escrow_state"), nullable=False, default=EscrowState.NOT_CREATED
    )
    last_reconciled_at: Mapped[datetime | None]
    # Escrow v2. contract_id + contract_version name the deployment this escrow lives on (v1 escrows stay there).
    contract_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    review_window_seconds: Mapped[int | None] = mapped_column(Integer)
    arbiter_addresses: Mapped[list[str]] = mapped_column(
        ARRAY(String(56)), nullable=False, default=list, server_default="{}"
    )
    arbiter_threshold: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )
    dispute_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    clock_reset_at: Mapped[int | None] = mapped_column(BigInteger)


class BlockchainTransaction(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_blockchain_transactions"
    __table_args__ = (
        UniqueConstraint(
            "network", "transaction_hash", name="uq_bountyflow_blockchain_transactions_network_hash"
        ),
        Index("ix_bountyflow_blockchain_tx_status", "status"),
        Index("ix_bountyflow_blockchain_tx_bounty_created", "bounty_id", "created_at"),
    )

    bounty_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="SET NULL"), index=True
    )
    transaction_hash: Mapped[str | None] = mapped_column(String(80))
    transaction_type: Mapped[TxType] = mapped_column(str_enum(TxType, "tx_type"), nullable=False)
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MONEY)
    asset_identifier: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[TxStatus] = mapped_column(str_enum(TxStatus, "tx_status"), nullable=False)
    source_address: Mapped[str | None] = mapped_column(String(56))
    destination_address: Mapped[str | None] = mapped_column(String(56))
    contract_id: Mapped[str | None] = mapped_column(String(56))
    function_name: Mapped[str | None] = mapped_column(String(40))
    unsigned_xdr: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None]
    fee_stroops: Mapped[int | None] = mapped_column(Integer)
    ledger_sequence: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(Text)
    verification_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    verification_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Links to the domain object this transaction settles.
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_bounty_submissions.id", ondelete="SET NULL"), index=True
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_bounty_assignments.id", ondelete="SET NULL"), index=True
    )
    dispute_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_disputes.id", ondelete="SET NULL")
    )

    bounty: Mapped[Bounty | None] = relationship(lazy="joined")
    user: Mapped[User | None] = relationship(lazy="joined")


class PaymentRecord(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "bountyflow_payment_records"
    __table_args__ = (
        # One payout per approved submission; a contributor is paid at most once per bounty, or once per
        # milestone on a milestone bounty.
        UniqueConstraint("submission_id", name="uq_bountyflow_payment_records_submission"),
        Index(
            "uq_bountyflow_payment_records_bounty_contributor",
            "bounty_id",
            "contributor_id",
            unique=True,
            postgresql_where=text("milestone_id IS NULL"),
        ),
        Index(
            "uq_bountyflow_payment_records_milestone",
            "milestone_id",
            unique=True,
            postgresql_where=text("milestone_id IS NOT NULL"),
        ),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="RESTRICT"), index=True
    )
    contributor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_users.id", ondelete="RESTRICT"), index=True
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounty_submissions.id", ondelete="RESTRICT")
    )
    blockchain_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_blockchain_transactions.id", ondelete="SET NULL")
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_bounty_milestones.id", ondelete="RESTRICT")
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    asset_identifier: Mapped[str] = mapped_column(String(80), nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus, "payment_status"), nullable=False, default=PaymentStatus.CREATED
    )
    settled_at: Mapped[datetime | None]

    contributor: Mapped[User] = relationship(lazy="joined", innerjoin=True)
    transaction: Mapped[BlockchainTransaction | None] = relationship(lazy="joined")
