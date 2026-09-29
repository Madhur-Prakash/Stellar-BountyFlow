"""Staff endpoints for compliance: deletion requests, sanctions screening, and legal document versions.

Reading needs ``audit:read`` (moderators and admins); changing the screening list or publishing legal versions
needs ``user:manage`` (admins).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.rbac import Permission
from app.core.schemas import Page, PageParams, UserSummary
from app.dependencies import SessionDep, require_permission
from app.modules.admin.models import AuditLog
from app.modules.bounties.repository import contains_pattern
from app.modules.compliance import deletion, legal, screening
from app.modules.compliance.models import DeletionStatus, ScreeningEntry, ScreeningSource
from app.modules.compliance.schemas import (
    AdminDeletionRequestOut,
    AdminLegalVersionOut,
    LegalVersionCreate,
    LegalVersionOut,
    ScreeningDecisionOut,
    ScreeningEntryCreate,
    ScreeningEntryOut,
    ScreeningEntryRemove,
    ScreeningListStatus,
    ScreeningStatusOut,
)
from app.modules.users.models import User

router = APIRouter(prefix="/admin/compliance", tags=["admin"])

Reader = Annotated[User, Depends(require_permission(Permission.AUDIT_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.USER_MANAGE))]


# --- Deletion requests --------------------------------------------------------------------


@router.get("/deletions", response_model=Page[AdminDeletionRequestOut])
async def list_deletions(
    session: SessionDep,
    user: Reader,
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[DeletionStatus | None, Query(alias="status")] = None,
) -> Page[AdminDeletionRequestOut]:
    return await deletion.list_requests(session, status_filter, params)


# --- Screening ------------------------------------------------------------------------------


async def _users(session: SessionDep, ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    return {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(ids)))).all()}


async def _entries_out(session: SessionDep, rows: list[ScreeningEntry]) -> list[ScreeningEntryOut]:
    people = await _users(session, {r.added_by_id for r in rows if r.added_by_id})
    return [
        ScreeningEntryOut(
            id=r.id,
            address=r.address,
            source=r.source,
            list_name=r.list_name,
            reason=r.reason,
            created_at=r.created_at,
            added_by=UserSummary.model_validate(people[r.added_by_id]) if r.added_by_id in people else None,
            removed_at=r.removed_at,
            removal_note=r.removal_note,
        )
        for r in rows
    ]


@router.get("/screening/status", response_model=ScreeningStatusOut)
async def screening_status(session: SessionDep, user: Reader) -> ScreeningStatusOut:
    settings = get_settings()
    counts = await screening.entry_counts(session)
    stored = await screening.list_status() or {}
    list_status = ScreeningListStatus(
        configured=bool(settings.sanctions_list_path or settings.sanctions_list_url),
        name=settings.sanctions_list_name,
        source=stored.get("source"),
        format=stored.get("format"),
        entries=counts[ScreeningSource.LIST.value],
        loaded_at=stored.get("loaded_at"),
        checked_at=stored.get("checked_at"),
        error=stored.get("error"),
    )
    return ScreeningStatusOut(
        enabled=settings.sanctions_screening_enabled,
        provider=screening.get_provider().name,
        manual_entries=counts[ScreeningSource.MANUAL.value],
        list_entries=counts[ScreeningSource.LIST.value],
        list=list_status,
    )


@router.get("/screening/entries", response_model=Page[ScreeningEntryOut])
async def list_entries(
    session: SessionDep,
    user: Reader,
    params: Annotated[PageParams, Depends()],
    q: Annotated[str | None, Query(max_length=56)] = None,
    source: ScreeningSource | None = None,
    include_removed: bool = False,
) -> Page[ScreeningEntryOut]:
    base = select(ScreeningEntry)
    if q:
        base = base.where(ScreeningEntry.address.ilike(contains_pattern(q.strip().upper()), escape="\\"))
    if source:
        base = base.where(ScreeningEntry.source == source)
    if not include_removed:
        base = base.where(ScreeningEntry.removed_at.is_(None))
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = list(
        (
            await session.scalars(
                base.order_by(ScreeningEntry.created_at.desc()).offset(params.offset).limit(params.page_size)
            )
        ).all()
    )
    return Page[ScreeningEntryOut].build(await _entries_out(session, rows), total, params)


@router.post("/screening/entries", response_model=ScreeningEntryOut, status_code=status.HTTP_201_CREATED)
async def add_entry(data: ScreeningEntryCreate, session: SessionDep, user: Manager) -> ScreeningEntryOut:
    entry = await screening.add_manual_entry(session, user.id, data.address, data.reason)
    return (await _entries_out(session, [entry]))[0]


@router.post("/screening/entries/{entry_id}/remove", response_model=ScreeningEntryOut)
async def remove_entry(
    entry_id: uuid.UUID, data: ScreeningEntryRemove, session: SessionDep, user: Manager
) -> ScreeningEntryOut:
    entry = await screening.remove_manual_entry(session, user.id, entry_id, data.note)
    return (await _entries_out(session, [entry]))[0]


@router.get("/screening/decisions", response_model=Page[ScreeningDecisionOut])
async def list_decisions(
    session: SessionDep,
    user: Reader,
    params: Annotated[PageParams, Depends()],
    result: Annotated[str | None, Query(pattern="^(blocked|cleared)$")] = "blocked",
    q: Annotated[str | None, Query(max_length=56)] = None,
) -> Page[ScreeningDecisionOut]:
    actions = [f"screening.{result}"] if result else ["screening.blocked", "screening.cleared"]
    base = select(AuditLog).where(AuditLog.action.in_(actions))
    if q:
        needle = q.strip().upper()
        base = base.where(
            or_(AuditLog.metadata_["address"].astext.ilike(contains_pattern(needle), escape="\\"))
        )
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(AuditLog.created_at.desc()).offset(params.offset).limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    items: list[ScreeningDecisionOut] = []
    for row in rows:
        meta: dict[str, Any] = row.metadata_ or {}
        items.append(
            ScreeningDecisionOut(
                id=row.id,
                created_at=row.created_at,
                result=row.action.removeprefix("screening."),
                address=str(meta.get("address", "")),
                context=str(meta.get("context", "")),
                provider=str(meta.get("provider", "")),
                user=UserSummary.model_validate(row.actor) if row.actor else None,
                matches=list(meta.get("matches") or []),
                bounty_id=meta.get("bounty_id"),
                request_id=row.request_id,
            )
        )
    return Page[ScreeningDecisionOut].build(items, total, params)


# --- Legal versions ---------------------------------------------------------------------------


async def _version_out(session: SessionDep, pairs: list[tuple[Any, int]]) -> list[AdminLegalVersionOut]:
    people = await _users(session, {v.published_by_id for v, _ in pairs if v.published_by_id})
    return [
        AdminLegalVersionOut(
            **LegalVersionOut.model_validate(v).model_dump(),
            published_by=UserSummary.model_validate(people[v.published_by_id])
            if v.published_by_id in people
            else None,
            accepted_count=count,
        )
        for v, count in pairs
    ]


@router.get("/legal/versions", response_model=list[AdminLegalVersionOut])
async def list_legal_versions(session: SessionDep, user: Reader) -> list[AdminLegalVersionOut]:
    return await _version_out(session, await legal.list_versions(session))


@router.post("/legal/versions", response_model=AdminLegalVersionOut, status_code=status.HTTP_201_CREATED)
async def publish_legal_version(
    data: LegalVersionCreate, session: SessionDep, user: Manager
) -> AdminLegalVersionOut:
    version = await legal.publish(session, user, data)
    return (await _version_out(session, [(version, 0)]))[0]


@router.post("/legal/versions/{version_id}/withdraw", response_model=AdminLegalVersionOut)
async def withdraw_legal_version(
    version_id: uuid.UUID, session: SessionDep, user: Manager
) -> AdminLegalVersionOut:
    version = await legal.withdraw(session, user, version_id)
    return (await _version_out(session, [(version, 0)]))[0]
