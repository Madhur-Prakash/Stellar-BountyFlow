"""Verifiable credential endpoints, plus the issuer's DID document at ``/.well-known/did.json``."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import NotFound
from app.core.rate_limit import client_ip, hit
from app.dependencies import CurrentUser, SessionDep
from app.modules.credentials import service
from app.modules.credentials.schemas import (
    CredentialOut,
    IssuedCredentialOut,
    IssuerInfo,
    VerificationReport,
    VerifyRequest,
)

router = APIRouter(tags=["credentials"])
well_known_router = APIRouter(tags=["credentials"])

VC_MEDIA_TYPE = "application/vc+json"


@well_known_router.get("/.well-known/did.json", response_model=dict[str, Any])
async def did_document() -> JSONResponse:
    document = service.issuer_did_document()
    if document is None:
        raise NotFound("This server does not issue credentials.")
    return JSONResponse(
        document,
        media_type="application/did+json",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"},
    )


@router.get("/credentials/issuer", response_model=IssuerInfo)
async def issuer() -> IssuerInfo:
    return service.issuer_info()


@router.get("/credentials/status/revocation", response_model=dict[str, Any])
async def revocation_list(session: SessionDep) -> JSONResponse:
    document = await service.status_list_credential(session)
    return JSONResponse(document, media_type=VC_MEDIA_TYPE, headers={"Access-Control-Allow-Origin": "*"})


@router.post("/credentials/verify", response_model=VerificationReport)
async def verify(data: VerifyRequest, request: Request, session: SessionDep) -> VerificationReport:
    # Public and side-effect free (CSRF-exempt): it only reads the database and the contract.
    await hit("credentials:verify", client_ip(request), 30, 300)
    return await service.verify(session, data.credential)


@router.post("/credentials/completions/{attestation_id}", response_model=IssuedCredentialOut)
async def issue_completion(
    attestation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> IssuedCredentialOut:
    await hit("credentials:issue", str(user.id), 60, 3600)
    return await service.issue_completion(session, user, attestation_id)


@router.post("/credentials/summary", response_model=IssuedCredentialOut)
async def issue_summary(user: CurrentUser, session: SessionDep) -> IssuedCredentialOut:
    await hit("credentials:issue", str(user.id), 60, 3600)
    return await service.issue_summary(session, user)


@router.get("/credentials/me", response_model=list[CredentialOut])
async def my_credentials(user: CurrentUser, session: SessionDep) -> list[CredentialOut]:
    return await service.my_credentials(session, user)


@router.get("/credentials/{credential_id}", response_model=IssuedCredentialOut)
async def get_credential(
    credential_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> IssuedCredentialOut:
    return await service.get_mine(session, user, credential_id)


@router.get("/credentials/{credential_id}/download", response_model=dict[str, Any])
async def download_credential(
    credential_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> JSONResponse:
    credential = await service.get_mine(session, user, credential_id)
    kind = "completion" if credential.kind.value == "COMPLETION" else "summary"
    filename = f"bountyflow-{kind}-credential-{str(credential.id)[:8]}.json"
    return JSONResponse(
        credential.document,
        media_type=VC_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
