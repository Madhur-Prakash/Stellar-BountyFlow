"""Attestation and reputation schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.core.schemas import APIModel, Asset, AssetAmount, Money, UserSummary, asset_from_identifier
from app.modules.reputation.chain import MAX_REASON_BYTES, AttestationConfig, get_config
from app.modules.reputation.models import AttestationStatus, CompletionAttestation


class AttestationBounty(APIModel):
    id: uuid.UUID
    slug: str
    title: str


class AttestationOut(APIModel):
    id: uuid.UUID
    onchain_id: int | None
    status: AttestationStatus
    network: str
    contributor: UserSummary
    contributor_address: str
    bounty: AttestationBounty
    amount: Money  # everything this contributor was paid on the bounty
    asset: Asset
    payments_count: int
    first_paid_at: datetime | None
    completed_at: datetime
    attested_at: datetime | None
    confirmed_at: datetime | None
    payout_tx_hash: str
    payout_explorer_url: str | None
    attestation_tx_hash: str | None
    attestation_explorer_url: str | None
    contract_id: str
    contract_explorer_url: str
    escrow_contract_id: str
    onchain_bounty_id: str
    token_contract_id: str
    revoked_at: datetime | None
    revocation_reason: str | None


def serialize_attestation(
    row: CompletionAttestation, config: AttestationConfig | None = None
) -> AttestationOut:
    config = config or get_config()
    base = config.network.explorer_base_url.rstrip("/")
    c = row.contributor
    b = row.bounty
    recorded = row.attestation_tx_hash and row.status != AttestationStatus.PENDING
    return AttestationOut(
        id=row.id,
        onchain_id=row.onchain_id,
        status=row.status,
        network=row.network,
        contributor=UserSummary(
            id=c.id, username=c.username, display_name=c.display_name, avatar_url=c.avatar_url
        ),
        contributor_address=row.contributor_address,
        bounty=AttestationBounty(id=b.id, slug=b.slug, title=b.title),
        amount=row.amount,
        asset=asset_from_identifier(row.asset_identifier),
        payments_count=row.payments_count,
        first_paid_at=row.first_paid_at,
        completed_at=row.completed_at,
        attested_at=row.attested_at,
        confirmed_at=row.confirmed_at,
        payout_tx_hash=row.payout_tx_hash,
        payout_explorer_url=f"{base}/tx/{row.payout_tx_hash}",
        attestation_tx_hash=row.attestation_tx_hash,
        attestation_explorer_url=f"{base}/tx/{row.attestation_tx_hash}" if recorded else None,
        contract_id=row.contract_id,
        contract_explorer_url=f"{base}/contract/{row.contract_id}",
        escrow_contract_id=row.escrow_contract_id,
        onchain_bounty_id=row.onchain_bounty_id,
        token_contract_id=row.token_contract_id,
        revoked_at=row.revoked_at,
        revocation_reason=row.revocation_reason,
    )


class ChainRead(APIModel):
    """The attestation as read from the contract just now (a simulation; nothing is signed)."""

    checked_at: datetime
    found: bool
    matches: bool
    revoked: bool
    record: dict[str, Any] | None
    error: str | None = None


class AttestationDetail(AttestationOut):
    chain: ChainRead | None


class ReputationSummary(APIModel):
    """A contributor's reputation from attested completions only (verified and recorded on-chain). ``earned``
    is grouped per asset; amounts of different assets are never added together."""

    enabled: bool
    attested_completions: int
    revoked: int
    earned: list[AssetAmount]
    first_completed_at: datetime | None
    last_completed_at: datetime | None
    network: str
    contract_id: str | None
    contract_explorer_url: str | None
    attester_address: str | None


class MyAttestationCounts(APIModel):
    confirmed: int
    in_progress: int
    revoked: int
    failed: int


class RevokeRequest(APIModel):
    reason: str = Field(min_length=3, max_length=MAX_REASON_BYTES)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 3:
            raise ValueError("Give a reason of at least 3 characters")
        if len(value.encode("utf-8")) > MAX_REASON_BYTES:
            raise ValueError(f"Keep the reason under {MAX_REASON_BYTES} bytes")
        return value


class BackfillResult(APIModel):
    queued: int


class ReconciliationReport(APIModel):
    checked: int
    matching: int
    mismatched: int
    missing: int
    revoked_on_chain: int
    by_status: dict[str, int]
    finished_at: datetime


class AdminAttestationOut(AttestationOut):
    attempts: int
    last_error: str | None
    chain_check: str | None
    chain_checked_at: datetime | None
