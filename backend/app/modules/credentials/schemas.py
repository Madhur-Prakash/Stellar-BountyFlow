"""Verifiable credential schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.core.schemas import APIModel
from app.modules.credentials.models import CredentialKind


class IssuerInfo(APIModel):
    enabled: bool
    did: str | None
    verification_method: str | None
    did_document_url: str | None
    status_list_url: str | None
    cryptosuite: str = "eddsa-jcs-2022"


class CredentialOut(APIModel):
    id: uuid.UUID
    credential_id: str  # the credential's own "id" (urn:uuid:…)
    kind: CredentialKind
    attestation_id: uuid.UUID | None
    attestation_count: int
    subject_did: str
    issuer_did: str
    issued_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None


class IssuedCredentialOut(CredentialOut):
    document: dict[str, Any]


class VerifyRequest(APIModel):
    credential: dict[str, Any] = Field(description="A verifiable credential (JSON) issued by this BountyFlow")


CheckId = Literal["format", "issuer", "signature", "validity", "status", "attestation"]
CheckStatus = Literal["pass", "fail", "skip"]


class VerificationCheck(APIModel):
    id: CheckId
    label: str
    status: CheckStatus
    detail: str


class VerifiedAttestation(APIModel):
    onchain_id: int
    contract_id: str
    matches: bool
    revoked: bool
    detail: str
    attestation_path: str | None  # the public attestation page on this site
    explorer_url: str | None  # the attestation transaction
    contract_explorer_url: str


class IssuerRef(APIModel):
    id: str | None
    name: str | None
    is_this_site: bool


class VerificationReport(APIModel):
    verified: bool
    checks: list[VerificationCheck]
    credential_id: str | None
    kind: Literal["completion", "summary"] | None
    issuer: IssuerRef
    subject: str | None
    valid_from: str | None
    attestations: list[VerifiedAttestation]
    checked_at: datetime
