"""On-chain completion attestations: one row per completed (bounty, contributor) pair.

A *completion* is a contributor whose position on a bounty is fully paid — the escrow contract reports them as
``Paid`` and their assignment is COMPLETED. That holds however the money moved: a single release, several
milestone payouts, one leg of a batch payout, a claim after the review window, or a paying dispute resolution.
The attested amount is therefore the **sum of that contributor's confirmed payments on the bounty**, in the
bounty's reward asset, and the individual payments are the evidence behind it.

The row is created when the completion is verified on-chain (or by the backfill job) and moves
PENDING -> SUBMITTED -> CONFIRMED once the registry's record has been read back and matches. Only CONFIRMED
(and later REVOKED) rows are ever shown as "completed on-chain". Rows are never deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import MONEY, Base, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum
from app.modules.bounties.models import Bounty
from app.modules.users.models import User


class AttestationStatus(StrEnum):
    PENDING = "PENDING"  # queued; nothing on-chain yet (or a failed attempt that will be retried)
    SUBMITTED = "SUBMITTED"  # the attest transaction reached the network; waiting for its outcome
    CONFIRMED = "CONFIRMED"  # read back from the contract and matching the completion
    REVOKING = "REVOKING"  # a revoke transaction is being submitted or confirmed
    REVOKED = "REVOKED"  # the contract reports the attestation revoked
    FAILED = "FAILED"  # permanent: the contract refused it, or retries were exhausted


class ChainCheck(StrEnum):
    """Result of the last reconciliation of this row against the contract."""

    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"


class CompletionAttestation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "completion_attestations"
    __table_args__ = (
        # One completion per contributor per bounty, however many transfers paid it (milestones, batch legs).
        UniqueConstraint("bounty_id", "contributor_id", name="uq_completion_attestations_bounty_contributor"),
        UniqueConstraint("network", "contract_id", "onchain_id", name="uq_completion_attestations_onchain"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("payments_count > 0", name="payments_counted"),
        Index("ix_completion_attestations_contributor_status", "contributor_id", "status"),
        Index("ix_completion_attestations_due", "status", "next_attempt_at"),
        Index("ix_completion_attestations_checked", "status", "chain_checked_at"),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="RESTRICT"), index=True)
    contributor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bounty_assignments.id", ondelete="SET NULL")
    )
    # The transaction whose verification completed the position (the last payment of the completion).
    payout_transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blockchain_transactions.id", ondelete="RESTRICT"), index=True
    )
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(56), nullable=False)  # the attestation registry
    # The address that was paid: a classic account (G…) or a passkey smart wallet contract (C…).
    contributor_address: Mapped[str] = mapped_column(String(56), nullable=False)
    onchain_bounty_id: Mapped[str] = mapped_column(String(64), nullable=False)  # hex BytesN<32>
    escrow_contract_id: Mapped[str] = mapped_column(String(56), nullable=False)
    payout_tx_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_identifier: Mapped[str] = mapped_column(String(80), nullable=False)  # "native" or CODE:ISSUER
    token_contract_id: Mapped[str] = mapped_column(String(56), nullable=False)  # the asset's SAC
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)  # total paid for this completion
    payments_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    first_paid_at: Mapped[datetime | None]
    completed_at: Mapped[datetime] = mapped_column(
        nullable=False
    )  # the completing payout's ledger close time

    status: Mapped[AttestationStatus] = mapped_column(
        str_enum(AttestationStatus, "attestation_status"), nullable=False, default=AttestationStatus.PENDING
    )
    onchain_id: Mapped[int | None] = mapped_column(BigInteger)
    attestation_tx_hash: Mapped[str | None] = mapped_column(String(64))
    attestation_ledger: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime | None]  # when the current attest/revoke transaction was sent
    attested_at: Mapped[datetime | None]  # ledger time recorded by the contract
    confirmed_at: Mapped[datetime | None]  # when BountyFlow verified the record on-chain

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)

    revocation_reason: Mapped[str | None] = mapped_column(String(200))
    revocation_tx_hash: Mapped[str | None] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None]
    revoked_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    chain_check: Mapped[ChainCheck | None] = mapped_column(str_enum(ChainCheck, "attestation_chain_check"))
    chain_checked_at: Mapped[datetime | None]

    bounty: Mapped[Bounty] = relationship(lazy="joined", innerjoin=True)
    contributor: Mapped[User] = relationship(lazy="joined", innerjoin=True, foreign_keys=[contributor_id])
