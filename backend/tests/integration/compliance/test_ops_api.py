"""The Prometheus endpoint, the reconciliation audit, and the staff operations snapshot."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utcnow
from app.modules.ops.health import job_health
from app.modules.payments.models import BlockchainTransaction, BountyEscrow
from app.modules.users.models import Role
from tests.integration.compliance.helpers import funded, requester, staff
from worker.jobs import reconciliation_audit
from worker.jobs.periodic import run_periodic


async def test_metrics_cover_requests_backlog_escrow_and_are_not_public(
    client_factory: Any, outbox_mail: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, wallet = await requester(client_factory, outbox_mail, "metrics")
    bounty = await funded(owner, wallet, reward_amount="3")
    await owner.get(f"/bounties/{bounty['id']}")

    probe = client_factory()
    response = await probe.http.get("/metrics")  # the test transport connects from 127.0.0.1
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    text = response.text
    assert (
        'bountyflow_http_requests_total{method="GET",route="/api/v1/bounties/{bounty_ref}",status="200"}'
        in text
    )
    assert "bountyflow_http_request_duration_seconds_bucket{" in text
    assert "bountyflow_outbox_backlog " in text
    assert 'bountyflow_escrow_held_amount{asset="native"} 3' in text
    assert 'bountyflow_metrics_collector_up{collector="outbox"} 1' in text
    assert "bountyflow_sponsor_configured 0" in text
    assert 'bountyflow_build_info{version="' in text

    proxied = await probe.http.get("/metrics", headers={"X-Forwarded-For": "203.0.113.7"})
    assert proxied.status_code == 404  # anything that came through a proxy is refused

    monkeypatch.setenv("METRICS_TOKEN", "m" * 32)
    get_settings.cache_clear()
    assert (await probe.http.get("/metrics")).status_code == 404
    assert (await probe.http.get("/metrics", headers={"Authorization": "Bearer wrong"})).status_code == 404
    authorised = await probe.http.get("/metrics", headers={"Authorization": f"Bearer {'m' * 32}"})
    assert authorised.status_code == 200


async def test_the_reconciliation_audit_reports_drift_without_changing_anything(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    owner, wallet = await requester(client_factory, outbox_mail, "audit")
    bounty = await funded(owner, wallet, reward_amount="5")
    bounty_id = uuid.UUID(bounty["id"])

    settling = await reconciliation_audit.run_audit_once()
    assert settling["skipped_settling"] == 1 and settling["checked"] == 0  # just confirmed: left alone

    await db_session.execute(
        update(BlockchainTransaction)
        .where(BlockchainTransaction.bounty_id == bounty_id)
        .values(confirmed_at=utcnow() - timedelta(hours=1))
    )
    await db_session.commit()
    clean = await reconciliation_audit.run_audit_once()
    assert clean["checked"] == 1 and clean["mismatches"] == 0 and clean["error"] is None

    await db_session.execute(
        update(BountyEscrow).where(BountyEscrow.bounty_id == bounty_id).values(funded_amount=Decimal("1"))
    )
    await db_session.commit()
    drift = await reconciliation_audit.run_audit_once()
    assert drift["mismatches"] == 1
    assert drift["details"][0]["fields"] == {"funded_amount": ["1.0000000", "5.0000000"]}
    escrow = await db_session.scalar(
        select(BountyEscrow)
        .where(BountyEscrow.bounty_id == bounty_id)
        .execution_options(populate_existing=True)
    )
    assert escrow is not None and escrow.funded_amount == Decimal("1")  # the audit never writes

    metrics = (await client_factory().http.get("/metrics")).text
    assert "bountyflow_reconciliation_mismatches 1" in metrics

    moderator = await staff(client_factory, db_session, Role.MODERATOR)
    snapshot = await moderator.get("/admin/ops/status")
    assert snapshot["reconciliation"]["mismatches"] == 1

    # The admin reconcile overwrites the database view with chain truth, and the next audit is clean.
    admin = await staff(client_factory, db_session)
    await admin.post(f"/admin/bounties/{bounty_id}/reconcile")
    assert (await reconciliation_audit.run_audit_once())["mismatches"] == 0


async def test_periodic_jobs_publish_their_health() -> None:
    stop = asyncio.Event()
    calls = 0

    async def job() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            stop.set()
        if calls == 1:
            raise RuntimeError("first run fails")

    await run_periodic("health-probe", 0.0, job, stop, lock_ttl=30)
    state = (await job_health())["health-probe"]
    assert state["runs"] == 2 and state["failures"] == 1 and state["consecutive_failures"] == 0
    assert state["last_success"] >= state["last_run"] and "first run fails" in state["last_error"]
