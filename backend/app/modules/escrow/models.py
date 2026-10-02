"""Escrow v2 records: bounty milestones and the verified mirror of arbiters' on-chain approvals."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MONEY, Base, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum


class MilestoneStatus(StrEnum):
    OPEN = "OPEN"
    PAID = "PAID"  # released on-chain (release_milestone, a batch leg, a claim or a whole-position release)
    SETTLED = "SETTLED"  # closed by an on-chain dispute resolution (the contributor may have received part)


class BountyMilestone(UUIDPrimaryKey, Timestamps, Base):
    """One milestone of a single-position bounty. ``position`` is the milestone's index in the escrow contract.
    ``status`` only leaves OPEN after the payout was verified on-chain."""

    __tablename__ = "bountyflow_bounty_milestones"
    __table_args__ = (
        UniqueConstraint("bounty_id", "position", name="uq_bountyflow_bounty_milestones_bounty_position"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("position >= 0 AND position < 20", name="position_range"),
        # The data export joins a requester's bounties and reads their milestones in order.
        Index("ix_bountyflow_bounty_milestones_bounty_position", "bounty_id", "position"),
    )

    bounty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_bounties.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    status: Mapped[MilestoneStatus] = mapped_column(
        str_enum(MilestoneStatus, "milestone_status"), nullable=False, default=MilestoneStatus.OPEN
    )
    paid_at: Mapped[datetime | None]
    # use_alter: blockchain_transactions -> bounty_submissions -> bounty_milestones -> blockchain_transactions
    # is a cycle, so this key is added after the tables exist.
    payout_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "bountyflow_blockchain_transactions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_bountyflow_bounty_milestones_payout_tx_blockchain_tx",
        )
    )


class DisputeVote(UUIDPrimaryKey, Timestamps, Base):
    """An arbiter's approval of a dispute resolution, recorded once the vote transaction is confirmed and the
    contract reports the vote (or its execution). The contract is authoritative; this is its mirror."""

    __tablename__ = "bountyflow_dispute_votes"
    __table_args__ = (
        UniqueConstraint(
            "dispute_id", "arbiter_address", "round", name="uq_bountyflow_dispute_votes_arbiter_round"
        ),
    )

    dispute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bountyflow_disputes.id", ondelete="CASCADE"), index=True
    )
    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bountyflow_bounties.id", ondelete="CASCADE"))
    arbiter_address: Mapped[str] = mapped_column(String(56), nullable=False)
    voter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bountyflow_users.id", ondelete="SET NULL"))
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    contributor_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bountyflow_blockchain_transactions.id", ondelete="SET NULL")
    )
