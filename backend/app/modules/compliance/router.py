"""Privacy and legal endpoints for signed-in users: data export, account deletion, terms acceptance."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.core.rate_limit import hit
from app.dependencies import CurrentUser, SessionDep
from app.modules.compliance import deletion, exports, legal
from app.modules.compliance.schemas import (
    DataExportOut,
    DeletionCreate,
    DeletionStatusOut,
    LegalAccept,
    LegalStatusOut,
    LegalVersionOut,
)

router = APIRouter(tags=["privacy"])


@router.get("/privacy/exports", response_model=list[DataExportOut])
async def list_exports(session: SessionDep, user: CurrentUser) -> list[DataExportOut]:
    return await exports.list_exports(session, user)


@router.post("/privacy/exports", response_model=DataExportOut, status_code=status.HTTP_202_ACCEPTED)
async def request_export(session: SessionDep, user: CurrentUser) -> DataExportOut:
    return await exports.request_export(session, user)


@router.get("/privacy/exports/{export_id}/download", response_class=Response)
async def download_export(
    export_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    expires: Annotated[int, Query(ge=0)],
    signature: Annotated[str, Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
) -> Response:
    """The archive as a JSON attachment. Needs the owner's session and a valid, unexpired signed link."""
    filename, body = await exports.download(session, user, export_id, expires, signature)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/privacy/deletion", response_model=DeletionStatusOut)
async def deletion_status(session: SessionDep, user: CurrentUser) -> DeletionStatusOut:
    return await deletion.get_status(session, user)


@router.post("/privacy/deletion", response_model=DeletionStatusOut, status_code=status.HTTP_201_CREATED)
async def request_deletion(data: DeletionCreate, session: SessionDep, user: CurrentUser) -> DeletionStatusOut:
    await hit("privacy:deletion", str(user.id), 10, 3600)
    return await deletion.request_deletion(session, user, data.password, data.reason)


@router.post("/privacy/deletion/cancel", response_model=DeletionStatusOut)
async def cancel_deletion(session: SessionDep, user: CurrentUser) -> DeletionStatusOut:
    return await deletion.cancel_deletion(session, user)


@router.get("/legal/versions", response_model=list[LegalVersionOut], tags=["legal"])
async def current_legal_versions(session: SessionDep) -> list[LegalVersionOut]:
    """The terms and privacy notice versions in effect (public)."""
    return await legal.current_versions(session)


@router.get("/legal/status", response_model=LegalStatusOut, tags=["legal"])
async def legal_status(session: SessionDep, user: CurrentUser) -> LegalStatusOut:
    return await legal.status(session, user)


@router.post("/legal/accept", response_model=LegalStatusOut, tags=["legal"])
async def accept_legal(data: LegalAccept, session: SessionDep, user: CurrentUser) -> LegalStatusOut:
    return await legal.accept(session, user, data.version_ids)
