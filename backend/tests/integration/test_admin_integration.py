"""Admin service against PostgreSQL: user management rules, reports, audit trail, overview."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.schemas import PageParams
from app.core.security import utcnow
from app.modules.admin import service as admin
from app.modules.admin.models import AuditLog, ReportStatus, ReportTarget
from app.modules.admin.schemas import AdminUserUpdate, ReportResolve
from app.modules.auth.models import UserSession
from app.modules.users.models import Role
from tests.integration.factories import make_bounty, make_user

pytestmark = pytest.mark.integration


async def add_session(session: AsyncSession, user_id: uuid.UUID) -> UserSession:
    s = UserSession(
        user_id=user_id,
        refresh_token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        expires_at=utcnow() + timedelta(days=1),
    )
    session.add(s)
    await session.flush()
    return s


async def test_admin_suspends_user_and_revokes_sessions(db_session: AsyncSession) -> None:
    actor = await make_user(db_session, role=Role.ADMIN)
    target = await make_user(db_session)
    user_session = await add_session(db_session, target.id)
    await db_session.commit()

    out = await admin.update_user(db_session, actor, target.id, AdminUserUpdate(is_active=False))
    assert out.is_active is False
    await db_session.refresh(user_session)
    assert user_session.revoked_at is not None
    assert user_session.revoked_reason == "account_suspended"
    actions = (await db_session.scalars(select(AuditLog.action).where(AuditLog.entity_id == target.id))).all()
    assert "admin.user_suspended" in actions


async def test_role_changes_are_admin_only_and_never_self(db_session: AsyncSession) -> None:
    admin_user = await make_user(db_session, role=Role.ADMIN)
    moderator = await make_user(db_session, role=Role.MODERATOR)
    target = await make_user(db_session)
    await db_session.commit()

    with pytest.raises(Forbidden):
        await admin.update_user(db_session, moderator, target.id, AdminUserUpdate(role=Role.MODERATOR))
    with pytest.raises(Forbidden):
        await admin.update_user(db_session, moderator, target.id, AdminUserUpdate(is_active=False))
    with pytest.raises(Forbidden):
        await admin.update_user(db_session, admin_user, admin_user.id, AdminUserUpdate(role=Role.USER))
    with pytest.raises(Forbidden):
        await admin.update_user(db_session, admin_user, admin_user.id, AdminUserUpdate(is_active=False))

    promoted = await admin.update_user(
        db_session, admin_user, target.id, AdminUserUpdate(role=Role.MODERATOR)
    )
    assert promoted.role == Role.MODERATOR
    # A no-op update is allowed and changes nothing.
    same = await admin.update_user(db_session, moderator, target.id, AdminUserUpdate(role=Role.MODERATOR))
    assert same.role == Role.MODERATOR
    with pytest.raises(NotFound):
        await admin.update_user(db_session, admin_user, uuid.uuid4(), AdminUserUpdate(is_active=False))


async def test_list_users_search_and_filters(db_session: AsyncSession) -> None:
    await make_user(db_session, role=Role.ADMIN, username="alice_admin")
    await make_user(db_session, username="bob_100%")
    await make_user(db_session, username="carol")
    await db_session.commit()
    page = await admin.list_users(db_session, PageParams(), q="100%")
    assert [u.username for u in page.items] == ["bob_100%"]
    admins = await admin.list_users(db_session, PageParams(), role=Role.ADMIN)
    assert [u.username for u in admins.items] == ["alice_admin"]
    assert admins.items[0].email_verified is True


async def test_reports_dedupe_resolve_and_audit(db_session: AsyncSession) -> None:
    reporter = await make_user(db_session)
    moderator = await make_user(db_session, role=Role.MODERATOR)
    bounty = await make_bounty(db_session, await make_user(db_session))
    await db_session.commit()

    first = await admin.create_report(
        db_session, reporter=reporter, target_type=ReportTarget.BOUNTY, target_id=bounty.id, reason=" Spam "
    )
    again = await admin.create_report(
        db_session,
        reporter=reporter,
        target_type=ReportTarget.BOUNTY,
        target_id=bounty.id,
        reason="Still spam",
    )
    assert again.id == first.id
    assert first.reason == "Spam"

    with pytest.raises(ValidationFailed):
        await admin.create_report(
            db_session, reporter=reporter, target_type=ReportTarget.USER, target_id=reporter.id, reason="me"
        )
    with pytest.raises(NotFound):
        await admin.create_report(
            db_session,
            reporter=reporter,
            target_type=ReportTarget.SUBMISSION,
            target_id=uuid.uuid4(),
            reason="x",
        )

    listing = await admin.list_reports(db_session, PageParams(), status=ReportStatus.OPEN)
    assert listing.total == 1
    assert listing.items[0].reporter.id == reporter.id

    resolved = await admin.resolve_report(
        db_session, moderator, first.id, ReportResolve(status=ReportStatus.ACTIONED, note="Hidden the bounty")
    )
    assert resolved.status == ReportStatus.ACTIONED
    assert resolved.resolved_at is not None
    with pytest.raises(InvalidStateTransition):
        await admin.resolve_report(
            db_session, moderator, first.id, ReportResolve(status=ReportStatus.DISMISSED, note="again")
        )

    # After resolution a new report on the same target is a new report.
    fresh = await admin.create_report(
        db_session,
        reporter=reporter,
        target_type=ReportTarget.BOUNTY,
        target_id=bounty.id,
        reason="Back again",
    )
    assert fresh.id != first.id

    logs = await admin.list_audit_logs(db_session, PageParams(), entity_type="report")
    assert {e.action for e in logs.items} == {"report.created", "report.resolved"}
    assert all(e.actor is not None for e in logs.items)


async def test_inactive_reporter_cannot_report(db_session: AsyncSession) -> None:
    reporter = await make_user(db_session, is_active=False)
    target = await make_user(db_session)
    await db_session.commit()
    with pytest.raises(Forbidden):
        await admin.create_report(
            db_session, reporter=reporter, target_type=ReportTarget.USER, target_id=target.id, reason="x"
        )


async def test_overview_reports_counts_and_health(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def healthy(*_: object, **__: object) -> bool:
        return True

    # No network in tests: Kafka and the Soroban RPC are reported healthy by stubs.
    monkeypatch.setattr(admin, "check_kafka", healthy)
    monkeypatch.setattr("app.blockchain.client.check_rpc", healthy)
    await make_user(db_session)
    await make_user(db_session, is_active=False)
    await db_session.commit()
    overview = await admin.overview(db_session)
    assert overview.counts.users_total == 2
    assert overview.counts.users_suspended == 1
    assert overview.health.database == "ok"
    assert overview.health.redis == "ok"  # fakeredis
    assert overview.health.worker == "error"  # no heartbeat in tests
    assert overview.worker_heartbeat_at is None
    assert overview.health.kafka in {"ok", "disabled"}
