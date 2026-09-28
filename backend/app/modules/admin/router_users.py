"""Admin endpoints for the platform overview, users, moderation reports, and the audit log.

Bounty, dispute, and transaction moderation endpoints live in ``app.modules.admin.router``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.rbac import Permission
from app.core.schemas import Page, PageParams
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.admin import service
from app.modules.admin.models import ReportStatus, ReportTarget
from app.modules.admin.schemas import (
    AdminOverview,
    AdminUserOut,
    AdminUserUpdate,
    AuditLogOut,
    ReportOut,
    ReportResolve,
)
from app.modules.users.models import Role, User

router = APIRouter(prefix="/admin", tags=["admin"])

HealthViewer = Annotated[User, Depends(require_permission(Permission.SYSTEM_HEALTH))]
UserViewer = Annotated[User, Depends(require_permission(Permission.USER_VIEW_ALL))]
ReportReviewer = Annotated[User, Depends(require_permission(Permission.REPORT_REVIEW))]
AuditReader = Annotated[User, Depends(require_permission(Permission.AUDIT_READ))]
Pagination = Annotated[PageParams, Depends()]


@router.get("/overview", response_model=AdminOverview)
async def overview(session: SessionDep, user: HealthViewer) -> AdminOverview:
    return await service.overview(session)


@router.get("/users", response_model=Page[AdminUserOut])
async def list_users(
    session: SessionDep,
    user: UserViewer,
    params: Pagination,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: Role | None = None,
    is_active: bool | None = None,
) -> Page[AdminUserOut]:
    return await service.list_users(session, params, q=q, role=role, is_active=is_active)


# Coarse guard: the caller must be able to manage accounts or assign roles; the service then checks the
# specific permission for each requested change (is_active -> user:manage, role -> user:assign_role).
@router.patch(
    "/users/{user_id}",
    response_model=AdminUserOut,
    dependencies=[Depends(require_permission(Permission.USER_VIEW_ALL))],
)
async def update_user(
    user_id: uuid.UUID, data: AdminUserUpdate, session: SessionDep, user: CurrentUser
) -> AdminUserOut:
    return await service.update_user(session, user, user_id, data)


@router.get("/reports", response_model=Page[ReportOut])
async def list_reports(
    session: SessionDep,
    user: ReportReviewer,
    params: Pagination,
    status: ReportStatus | None = None,
    target_type: ReportTarget | None = None,
) -> Page[ReportOut]:
    return await service.list_reports(session, params, status=status, target_type=target_type)


@router.post("/reports/{report_id}/resolve", response_model=ReportOut)
async def resolve_report(
    report_id: uuid.UUID, data: ReportResolve, session: SessionDep, user: ReportReviewer
) -> ReportOut:
    return await service.resolve_report(session, user, report_id, data)


@router.get("/audit-logs", response_model=Page[AuditLogOut])
async def list_audit_logs(
    session: SessionDep,
    user: AuditReader,
    params: Pagination,
    entity_type: Annotated[str | None, Query(max_length=32)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Page[AuditLogOut]:
    return await service.list_audit_logs(
        session, params, entity_type=entity_type, action=action, entity_id=entity_id, actor_id=actor_id
    )
