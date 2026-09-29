"""Funding, payout, and blockchain transaction schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, Field

from app.blockchain.config import get_network
from app.core.money import fmt, parse_amount
from app.core.schemas import APIModel, Asset, Money, OptionalMoney, UserSummary, asset_from_identifier
from app.modules.payments.models import BlockchainTransaction, PaymentRecord, PaymentStatus, TxStatus, TxType


class ChainAction(StrEnum):
    FUND = "FUND"
    ASSIGN = "ASSIGN"
    PAYOUT = "PAYOUT"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    CONSENT_CANCEL = "CONSENT_CANCEL"
    REFUND = "REFUND"
    RAISE_DISPUTE = "RAISE_DISPUTE"
    RESOLVE_DISPUTE = "RESOLVE_DISPUTE"
    # Escrow v2 (app/modules/escrow/chain.py)
    MILESTONE_PAYOUT = "MILESTONE_PAYOUT"
    BATCH_PAYOUT = "BATCH_PAYOUT"
    SUBMIT_WORK = "SUBMIT_WORK"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT_SUBMISSION = "REJECT_SUBMISSION"
    CLAIM = "CLAIM"
    DISPUTE_VOTE = "DISPUTE_VOTE"


class BlockchainTransactionOut(APIModel):
    id: uuid.UUID
    bounty_id: uuid.UUID | None
    bounty_title: str | None
    bounty_slug: str | None = None
    user: UserSummary | None
    transaction_hash: str | None
    transaction_type: TxType
    network: str
    amount: OptionalMoney
    asset: Asset | None
    status: TxStatus
    source_address: str | None
    destination_address: str | None
    contract_id: str | None = None
    function_name: str | None = None
    ledger_sequence: int | None
    submitted_at: datetime | None
    confirmed_at: datetime | None
    failure_reason: str | None
    explorer_url: str | None
    created_at: datetime
    # The platform sponsor paid (or bid to pay) this transaction's network fee.
    fee_sponsored: bool = False


def serialize_tx(tx: BlockchainTransaction) -> BlockchainTransactionOut:
    network = get_network()
    user = tx.user
    return BlockchainTransactionOut(
        id=tx.id,
        bounty_id=tx.bounty_id,
        bounty_title=tx.bounty.title if tx.bounty else None,
        bounty_slug=tx.bounty.slug if tx.bounty else None,
        user=UserSummary(
            id=user.id, username=user.username, display_name=user.display_name, avatar_url=user.avatar_url
        )
        if user
        else None,
        transaction_hash=tx.transaction_hash,
        transaction_type=tx.transaction_type,
        network=tx.network,
        amount=tx.amount,
        asset=asset_from_identifier(tx.asset_identifier) if tx.asset_identifier else None,
        status=tx.status,
        source_address=tx.source_address,
        destination_address=tx.destination_address,
        contract_id=tx.contract_id,
        function_name=tx.function_name,
        ledger_sequence=tx.ledger_sequence,
        submitted_at=tx.submitted_at,
        confirmed_at=tx.confirmed_at,
        failure_reason=tx.failure_reason,
        explorer_url=None
        if tx.status in (TxStatus.SIGNATURE_REQUIRED, TxStatus.EXPIRED, TxStatus.CREATED)
        else network.tx_url(tx.transaction_hash),
        created_at=tx.created_at,
        fee_sponsored=bool((tx.verification_metadata or {}).get("sponsorship")),
    )


class PaymentRecordOut(APIModel):
    id: uuid.UUID
    bounty_id: uuid.UUID
    bounty_title: str | None = None
    bounty_slug: str | None = None
    contributor: UserSummary
    submission_id: uuid.UUID
    amount: Money
    asset: Asset
    payment_status: PaymentStatus
    transaction: BlockchainTransactionOut | None
    created_at: datetime
    settled_at: datetime | None
    milestone_id: uuid.UUID | None = None


def serialize_payment(
    p: PaymentRecord, bounty_title: str | None = None, bounty_slug: str | None = None
) -> PaymentRecordOut:
    c = p.contributor
    return PaymentRecordOut(
        id=p.id,
        bounty_id=p.bounty_id,
        bounty_title=bounty_title,
        bounty_slug=bounty_slug,
        contributor=UserSummary(
            id=c.id, username=c.username, display_name=c.display_name, avatar_url=c.avatar_url
        ),
        submission_id=p.submission_id,
        amount=p.amount,
        asset=asset_from_identifier(p.asset_identifier),
        payment_status=p.payment_status,
        transaction=serialize_tx(p.transaction) if p.transaction else None,
        created_at=p.created_at,
        settled_at=p.settled_at,
        milestone_id=p.milestone_id,
    )


def _amount_string(value: str | None) -> str | None:
    """Optional deposit amount: a positive decimal string with at most 7 fractional digits (else 422)."""
    if value is None or not value.strip():
        return None
    return fmt(parse_amount(value))


AmountString = Annotated[str | None, AfterValidator(_amount_string)]


class PrepareRequest(APIModel):
    action: ChainAction
    wallet_address: str = Field(min_length=56, max_length=56)
    submission_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    dispute_id: uuid.UUID | None = None
    amount: AmountString = None
    # BATCH_PAYOUT: the approved submissions paid in one call.
    submission_ids: list[uuid.UUID] | None = Field(default=None, max_length=10)
    # REQUEST_CHANGES / REJECT_SUBMISSION: applied to the submission once the answer is confirmed on-chain.
    feedback: str | None = Field(default=None, min_length=5, max_length=5000)


class FundingPrepareRequest(APIModel):
    wallet_address: str = Field(min_length=56, max_length=56)
    amount: AmountString = None


class PayoutPrepareRequest(APIModel):
    wallet_address: str = Field(min_length=56, max_length=56)
    submission_id: uuid.UUID


class SubmitRequest(APIModel):
    signed_xdr: str = Field(min_length=1, max_length=100_000)


class AliasSubmitRequest(SubmitRequest):
    transaction_id: uuid.UUID


class TxSummary(APIModel):
    action: ChainAction
    description: str
    amount: OptionalMoney
    asset: Asset | None
    fee_estimate_stroops: str | None
    contract_id: str | None
    function_name: str
    # BountyFlow's sponsor is expected to pay the network fee (decided again when the transaction is submitted).
    fee_sponsored: bool = False


class PreparedTransactionOut(APIModel):
    transaction: BlockchainTransactionOut
    unsigned_xdr: str | None
    network_passphrase: str
    network: str
    summary: TxSummary
    expires_at: datetime


class FundingOut(APIModel):
    funding_status: str
    escrow: dict[str, object] | None
    transactions: list[BlockchainTransactionOut]
