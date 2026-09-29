"""Dispute endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.rate_limit import rate_limit
from app.core.rbac import Permission
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.disputes import service
from app.modules.disputes.schemas import DisputeCreate, DisputeOut, EvidenceCreate, ResolveRequest
from app.modules.users.models import User

router = APIRouter(tags=["disputes"])


@router.post(
    "/bounties/{bounty_id}/disputes",
    response_model=DisputeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("dispute:create", 10, 3600))],
)
async def raise_dispute(
    bounty_id: uuid.UUID,
    data: DisputeCreate,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.DISPUTE_RAISE))],
) -> DisputeOut:
    return await service.raise_dispute(session, user, bounty_id, data)


@router.get("/disputes/me", response_model=list[DisputeOut])
async def mine(session: SessionDep, user: CurrentUser) -> list[DisputeOut]:
    return await service.mine(session, user)


@router.get("/disputes/{dispute_id}", response_model=DisputeOut)
async def get(dispute_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> DisputeOut:
    return await service.get(session, user, dispute_id)


@router.post("/disputes/{dispute_id}/evidence", response_model=DisputeOut)
async def add_evidence(
    dispute_id: uuid.UUID, data: EvidenceCreate, session: SessionDep, user: CurrentUser
) -> DisputeOut:
    return await service.add_evidence(session, user, dispute_id, data)


@router.post("/disputes/{dispute_id}/assign", response_model=DisputeOut)
async def assign(
    dispute_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.DISPUTE_RESOLVE))],
) -> DisputeOut:
    return await service.assign_self(session, user, dispute_id)


@router.post("/disputes/{dispute_id}/resolve", response_model=DisputeOut)
async def resolve(
    dispute_id: uuid.UUID,
    data: ResolveRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.DISPUTE_RESOLVE))],
) -> DisputeOut:
    return await service.resolve(
        session, user, dispute_id, data.resolution, data.note, data.contributor_amount
    )
