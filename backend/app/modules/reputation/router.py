"""Attestation and reputation endpoints: public profile data, the owner's view, and staff operations."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.core.rate_limit import client_ip, hit
from app.core.rbac import Permission
from app.core.schemas import Page, PageParams
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.reputation import service
from app.modules.reputation.models import AttestationStatus
from app.modules.reputation.schemas import (
    AdminAttestationOut,
    AttestationDetail,
    AttestationOut,
    BackfillResult,
    MyAttestationCounts,
    ReconciliationReport,
    ReputationSummary,
    RevokeRequest,
)
from app.modules.users.models import User

router = APIRouter(tags=["reputation"])

StaffUser = Annotated[User, Depends(require_permission(Permission.SYSTEM_HEALTH))]


@router.get("/users/{username}/reputation", response_model=ReputationSummary)
async def user_reputation(username: str, session: SessionDep) -> ReputationSummary:
    return await service.summary(session, username)


@router.get("/users/{username}/attestations", response_model=Page[AttestationOut])
async def user_attestations(
    username: str, session: SessionDep, params: Annotated[PageParams, Depends()]
) -> Page[AttestationOut]:
    return await service.public_attestations(session, username, params)


@router.get("/attestations/{attestation_ref}", response_model=AttestationDetail)
async def get_attestation(attestation_ref: str, request: Request, session: SessionDep) -> AttestationDetail:
    await hit("attestation:read", client_ip(request), 120, 60)  # each uncached view reads the contract
    return await service.public_attestation(session, attestation_ref)


@router.get("/reputation/me/attestations", response_model=Page[AttestationOut])
async def my_attestations(
    user: CurrentUser, session: SessionDep, params: Annotated[PageParams, Depends()]
) -> Page[AttestationOut]:
    return await service.my_attestations(session, user, params)


@router.get("/reputation/me/counts", response_model=MyAttestationCounts)
async def my_counts(user: CurrentUser, session: SessionDep) -> MyAttestationCounts:
    return await service.my_counts(session, user)


# --- Staff ------------------------------------------------------------------------------


@router.get("/admin/attestations", response_model=Page[AdminAttestationOut], tags=["admin"])
async def admin_attestations(
    _staff: StaffUser,
    session: SessionDep,
    params: Annotated[PageParams, Depends()],
    status: Annotated[AttestationStatus | None, Query()] = None,
) -> Page[AdminAttestationOut]:
    return await service.admin_list(session, status, params)


@router.post("/admin/attestations/backfill", response_model=BackfillResult, tags=["admin"])
async def admin_backfill(_staff: StaffUser, session: SessionDep) -> BackfillResult:
    service._require_writes()
    return BackfillResult(queued=await service.backfill(session, limit=500))


@router.post("/admin/attestations/reconcile", response_model=ReconciliationReport, tags=["admin"])
async def admin_reconcile(_staff: StaffUser, session: SessionDep) -> ReconciliationReport:
    return await service.reconcile(session, limit=200)


@router.get("/admin/attestations/reconciliation", response_model=ReconciliationReport | None, tags=["admin"])
async def admin_last_reconciliation(_staff: StaffUser) -> ReconciliationReport | None:
    return await service.last_reconciliation()


@router.post("/admin/attestations/{attestation_id}/revoke", response_model=AttestationOut, tags=["admin"])
async def admin_revoke(
    attestation_id: uuid.UUID,
    data: RevokeRequest,
    session: SessionDep,
    staff: Annotated[User, Depends(require_permission(Permission.USER_MANAGE))],
) -> AttestationOut:
    return await service.request_revocation(session, staff, attestation_id, data.reason)


@router.post("/admin/attestations/{attestation_id}/retry", response_model=AttestationOut, tags=["admin"])
async def admin_retry(attestation_id: uuid.UUID, _staff: StaffUser, session: SessionDep) -> AttestationOut:
    return await service.retry(session, attestation_id)
