"""Admin use cases: platform overview, user management, moderation reports, and audit log browsing."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.config import get_network
from app.cache import keys
from app.cache.invalidation import invalidate_profile
from app.cache.redis import check_redis, get_redis
from app.core.config import get_settings
from app.core.exceptions import Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.rbac import Permission, can_assign_role, ensure_permission
from app.core.schemas import Page, PageParams, UserSummary
from app.core.security import utcnow
from app.db.health import check_database
from app.messaging.kafka import check_kafka
from app.messaging.models import OutboxEvent
from app.modules.admin import audit
from app.modules.admin.models import AuditLog, ReportStatus, ReportTarget, UserReport
from app.modules.admin.schemas import (
    AdminOverview,
    AdminUserOut,
    AdminUserUpdate,
    AuditLogOut,
    HealthSnapshot,
    HealthState,
    OverviewCounts,
    ReportOut,
    ReportResolve,
    ReportTargetSummary,
)
from app.modules.analytics.rules import OPEN_STATUSES
from app.modules.auth.repository import revoke_all_sessions
from app.modules.bounties.models import Bounty
from app.modules.disputes.models import Dispute, DisputeStatus
from app.modules.payments.models import BlockchainTransaction, TxStatus
from app.modules.qa.models import BountyQAPost
from app.modules.submissions.models import BountySubmission
from app.modules.users.models import Role, User

logger = get_logger(__name__)

OPEN_REPORT_STATUSES = (ReportStatus.OPEN, ReportStatus.REVIEWING)
HEARTBEAT_WORKER = "main"


def _like(term: str) -> str:
    escaped = term.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _count(session: AsyncSession, stmt: Select[Any]) -> int:
    return int(await session.scalar(stmt) or 0)


# --- Overview ----------------------------------------------------------------------------------


def _state(ok: bool | BaseException) -> HealthState:
    return "ok" if ok is True else "error"


async def _worker_heartbeat() -> datetime | None:
    try:
        raw = await get_redis().get(keys.worker_heartbeat(HEARTBEAT_WORKER))
    except Exception:
        return None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(json.loads(raw)["at"])
    except (ValueError, KeyError, TypeError):
        return None


async def overview(session: AsyncSession) -> AdminOverview:
    from app.blockchain.client import check_rpc

    settings = get_settings()
    net = get_network()
    now = utcnow()
    db_ok, redis_ok, kafka_ok, rpc_ok, heartbeat = await asyncio.gather(
        check_database(),
        check_redis(),
        check_kafka() if settings.kafka_enabled else asyncio.sleep(0, result=False),
        check_rpc(),
        _worker_heartbeat(),
        return_exceptions=True,
    )
    user_row = (
        await session.execute(
            select(
                func.count(User.id),
                func.count(User.id).filter(User.last_login_at >= now - timedelta(days=30)),
                func.count(User.id).filter(User.is_active.is_(False)),
            )
        )
    ).one()
    bounty_row = (
        await session.execute(
            select(
                func.count(Bounty.id),
                func.count(Bounty.id).filter(Bounty.status.in_(OPEN_STATUSES)),
                func.count(Bounty.id).filter(Bounty.is_hidden.is_(True)),
            )
        )
    ).one()
    counts = OverviewCounts(
        users_total=user_row[0],
        users_active_30d=user_row[1],
        users_suspended=user_row[2],
        bounties_total=bounty_row[0],
        bounties_open=bounty_row[1],
        bounties_hidden=bounty_row[2],
        open_reports=await _count(
            session, select(func.count(UserReport.id)).where(UserReport.status.in_(OPEN_REPORT_STATUSES))
        ),
        open_disputes=await _count(
            session,
            select(func.count(Dispute.id)).where(
                Dispute.status.in_([DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW])
            ),
        ),
        pending_transactions=await _count(
            session,
            select(func.count(BlockchainTransaction.id)).where(
                BlockchainTransaction.status == TxStatus.SUBMITTED
            ),
        ),
        failed_transactions_24h=await _count(
            session,
            select(func.count(BlockchainTransaction.id)).where(
                BlockchainTransaction.status == TxStatus.FAILED,
                BlockchainTransaction.created_at >= now - timedelta(hours=24),
            ),
        ),
        unpublished_outbox_events=await _count(
            session, select(func.count(OutboxEvent.id)).where(OutboxEvent.published_at.is_(None))
        ),
    )
    heartbeat_at = heartbeat if isinstance(heartbeat, datetime) else None
    health = HealthSnapshot(
        database=_state(db_ok),
        redis=_state(redis_ok),
        kafka=_state(kafka_ok) if settings.kafka_enabled else "disabled",
        blockchain_rpc=_state(rpc_ok),
        worker="ok" if heartbeat_at is not None else "error",
    )
    return AdminOverview(
        generated_at=now,
        network=net.network,
        counts=counts,
        health=health,
        worker_heartbeat_at=heartbeat_at,
    )


# --- Users ----------------------------------------------------------------------------------------


def admin_user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        email_verified=user.email_verified_at is not None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


async def list_users(
    session: AsyncSession,
    params: PageParams,
    *,
    q: str | None = None,
    role: Role | None = None,
    is_active: bool | None = None,
) -> Page[AdminUserOut]:
    conditions: list[Any] = []
    if q and q.strip():
        pattern = _like(q)
        conditions.append(
            or_(
                User.username.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
                User.normalized_email.ilike(pattern, escape="\\"),
            )
        )
    if role is not None:
        conditions.append(User.role == role)
    if is_active is not None:
        conditions.append(User.is_active.is_(is_active))
    total = await _count(session, select(func.count(User.id)).where(*conditions))
    rows = await session.scalars(
        select(User)
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id)
        .offset(params.offset)
        .limit(params.page_size)
    )
    return Page[AdminUserOut].build([admin_user_out(u) for u in rows.all()], total, params)


async def update_user(
    session: AsyncSession, actor: User, user_id: uuid.UUID, data: AdminUserUpdate
) -> AdminUserOut:
    target = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise NotFound("User not found.")
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    wants_active = "is_active" in changes and changes["is_active"] != target.is_active
    wants_role = "role" in changes and changes["role"] != target.role
    if not wants_active and not wants_role:
        return admin_user_out(target)
    if target.id == actor.id:
        raise Forbidden("You cannot change your own role or account status.")

    now = utcnow()
    if wants_role:
        new_role = Role(changes["role"])
        if not can_assign_role(actor, target, new_role):
            raise Forbidden(
                "Only administrators can change roles.",
                details={"required_permission": Permission.USER_ASSIGN_ROLE.value},
            )
        previous = target.role
        target.role = new_role
        audit.record(
            session,
            actor_id=actor.id,
            action="admin.user_role_changed",
            entity_type="user",
            entity_id=target.id,
            metadata={"from": previous.value, "to": new_role.value},
            is_public=False,
        )
    if wants_active:
        ensure_permission(
            actor, Permission.USER_MANAGE, "Only administrators can suspend or reactivate accounts."
        )
        target.is_active = bool(changes["is_active"])
        if not target.is_active:
            await revoke_all_sessions(session, target.id, "account_suspended", now)
        audit.record(
            session,
            actor_id=actor.id,
            action="admin.user_reactivated" if target.is_active else "admin.user_suspended",
            entity_type="user",
            entity_id=target.id,
            metadata={"username": target.username},
            is_public=False,
        )
    await session.commit()
    await session.refresh(target)
    await invalidate_profile(target.username)
    logger.info(
        "admin_user_updated", target_id=str(target.id), role_changed=wants_role, status_changed=wants_active
    )
    return admin_user_out(target)


# --- Reports ----------------------------------------------------------------------------------


def report_out(report: UserReport) -> ReportOut:
    return ReportOut(
        id=report.id,
        reporter=UserSummary.model_validate(report.reporter),
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        status=report.status,
        created_at=report.created_at,
        resolution_note=report.resolution_note,
        resolved_at=report.resolved_at,
    )


async def _target_exists(session: AsyncSession, target_type: ReportTarget, target_id: uuid.UUID) -> bool:
    model: Any = {
        ReportTarget.USER: User,
        ReportTarget.BOUNTY: Bounty,
        ReportTarget.SUBMISSION: BountySubmission,
        ReportTarget.QA_POST: BountyQAPost,
    }[target_type]
    return (await session.scalar(select(model.id).where(model.id == target_id))) is not None


async def create_report(
    session: AsyncSession, *, reporter: User, target_type: ReportTarget, target_id: uuid.UUID, reason: str
) -> UserReport:
    """File a moderation report. A reporter's open report on the same target is returned instead of creating
    a duplicate. Commits."""
    ensure_permission(reporter, Permission.REPORT_CREATE)
    reason = reason.strip()
    if not reason:
        raise ValidationFailed(
            "Please describe the problem.", details=[{"field": "reason", "message": "Required"}]
        )
    if target_type == ReportTarget.USER and target_id == reporter.id:
        raise ValidationFailed("You cannot report yourself.")
    if not await _target_exists(session, target_type, target_id):
        raise NotFound("The reported item was not found.")
    existing = await session.scalar(
        select(UserReport).where(
            UserReport.reporter_id == reporter.id,
            UserReport.target_type == target_type,
            UserReport.target_id == target_id,
            UserReport.status.in_(OPEN_REPORT_STATUSES),
        )
    )
    if existing is not None:
        return existing
    report = UserReport(
        id=uuid.uuid4(),
        reporter_id=reporter.id,
        target_type=target_type,
        target_id=target_id,
        reason=reason[:5000],
        status=ReportStatus.OPEN,
    )
    session.add(report)
    audit.record(
        session,
        actor_id=reporter.id,
        action="report.created",
        entity_type="report",
        entity_id=report.id,
        bounty_id=target_id if target_type == ReportTarget.BOUNTY else None,
        metadata={"target_type": target_type.value, "target_id": str(target_id)},
        is_public=False,
    )
    await session.commit()
    await session.refresh(report)
    return report


async def list_reports(
    session: AsyncSession,
    params: PageParams,
    *,
    status: ReportStatus | None = None,
    target_type: ReportTarget | None = None,
) -> Page[ReportOut]:
    conditions: list[Any] = []
    if status is not None:
        conditions.append(UserReport.status == status)
    if target_type is not None:
        conditions.append(UserReport.target_type == target_type)
    total = await _count(session, select(func.count(UserReport.id)).where(*conditions))
    rows = await session.scalars(
        select(UserReport)
        .where(*conditions)
        .order_by(UserReport.created_at.desc(), UserReport.id)
        .offset(params.offset)
        .limit(params.page_size)
    )
    reports = rows.unique().all()
    items = [report_out(r) for r in reports]
    await _attach_target_summaries(session, items)
    return Page[ReportOut].build(items, total, params)


async def _attach_target_summaries(session: AsyncSession, items: list[ReportOut]) -> None:
    """Q&A posts are reported by id; show the moderator where the post is and what it says."""
    from app.modules.qa.service import report_target_summaries  # qa depends on this module

    post_ids = [r.target_id for r in items if r.target_type == ReportTarget.QA_POST]
    summaries = await report_target_summaries(session, post_ids)
    for item in items:
        summary = summaries.get(item.target_id) if item.target_type == ReportTarget.QA_POST else None
        if summary is not None:
            item.target_summary = ReportTargetSummary.model_validate(summary)


async def resolve_report(
    session: AsyncSession, actor: User, report_id: uuid.UUID, data: ReportResolve
) -> ReportOut:
    report = await session.scalar(
        select(UserReport).where(UserReport.id == report_id).with_for_update(of=UserReport)
    )
    if report is None:
        raise NotFound("Report not found.")
    if report.status not in OPEN_REPORT_STATUSES:
        raise InvalidStateTransition(f"This report is already {report.status.value.lower()}.")
    report.status = ReportStatus(data.status)
    report.resolution_note = data.note
    report.resolved_by_id = actor.id
    report.resolved_at = utcnow()
    audit.record(
        session,
        actor_id=actor.id,
        action="report.resolved",
        entity_type="report",
        entity_id=report.id,
        bounty_id=report.target_id if report.target_type == ReportTarget.BOUNTY else None,
        metadata={
            "status": report.status.value,
            "target_type": report.target_type.value,
            "target_id": str(report.target_id),
        },
        is_public=False,
    )
    await session.commit()
    await session.refresh(report)
    return report_out(report)


# --- Audit log ---------------------------------------------------------------------------------


def audit_out(entry: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=entry.id,
        actor=UserSummary.model_validate(entry.actor) if entry.actor else None,
        action=entry.action,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        bounty_id=entry.bounty_id,
        metadata=entry.metadata_ or {},
        created_at=entry.created_at,
    )


async def list_audit_logs(
    session: AsyncSession,
    params: PageParams,
    *,
    entity_type: str | None = None,
    action: str | None = None,
    entity_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> Page[AuditLogOut]:
    conditions: list[Any] = []
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if action:
        conditions.append(AuditLog.action == action)
    if entity_id:
        conditions.append(AuditLog.entity_id == entity_id)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    total = await _count(session, select(func.count(AuditLog.id)).where(*conditions))
    rows = await session.scalars(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset(params.offset)
        .limit(params.page_size)
    )
    return Page[AuditLogOut].build([audit_out(e) for e in rows.unique().all()], total, params)
