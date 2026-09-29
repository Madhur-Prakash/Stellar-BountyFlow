"""Terms and privacy notice versions: publishing, the workspace gate, advance notice, and acceptance records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.compliance.models import LegalAcceptance
from tests.integration.api.conftest import drain_events, register
from tests.integration.compliance.helpers import handle, staff


async def test_a_new_version_gates_existing_users_until_they_accept(
    client_factory: Any, db_session: AsyncSession
) -> None:
    admin = await staff(client_factory, db_session)
    user = client_factory()
    await register(user, handle("member"))
    status = await user.get("/legal/status")
    assert status["needs_acceptance"] is False and status["upcoming_pending"] is False
    assert {d["document"] for d in status["documents"]} == {"TERMS", "PRIVACY"}

    terms = await admin.post(
        "/admin/compliance/legal/versions",
        {"document": "TERMS", "version": "2026-10", "summary": "Clearer rules on disputes and refunds."},
        expected=201,
    )
    assert terms["published_by"]["username"] == admin.me["username"]
    public = await client_factory().get("/legal/versions")
    assert [(v["document"], v["version"]) for v in public] == [("TERMS", "2026-10")]

    gated = await user.get("/legal/status")
    assert gated["needs_acceptance"] is True
    [doc] = [d for d in gated["documents"] if d["document"] == "TERMS"]
    assert doc["current"]["id"] == terms["id"] and doc["accepted_current"] is False

    unknown = await user.request("POST", "/legal/accept", json={"version_ids": [str(uuid.uuid4())]})
    assert unknown.status_code == 422
    accepted = await user.post("/legal/accept", {"version_ids": [terms["id"]]})
    assert accepted["needs_acceptance"] is False
    row = await db_session.scalar(
        select(LegalAcceptance).where(LegalAcceptance.user_id == uuid.UUID(user.me["id"]))
    )
    assert row is not None and row.source == "prompt"

    # Signing up after a version took effect is acceptance of it; the worker also records it explicitly.
    newcomer = client_factory()
    await register(newcomer, handle("newcomer"))
    assert (await newcomer.get("/legal/status"))["needs_acceptance"] is False
    await drain_events()
    recorded = await db_session.scalar(
        select(LegalAcceptance).where(LegalAcceptance.user_id == uuid.UUID(newcomer.me["id"]))
    )
    assert recorded is not None and recorded.source == "registration"

    listed = await admin.get("/admin/compliance/legal/versions")
    assert listed[0]["accepted_count"] == 2


async def test_a_scheduled_version_is_announced_and_can_be_withdrawn(
    client_factory: Any, db_session: AsyncSession
) -> None:
    admin = await staff(client_factory, db_session)
    user = client_factory()
    await register(user, handle("reader"))
    effective = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    scheduled = await admin.post(
        "/admin/compliance/legal/versions",
        {
            "document": "PRIVACY",
            "version": "2026-11",
            "summary": "We now keep payout records for seven years.",
            "effective_at": effective,
        },
        expected=201,
    )
    status = await user.get("/legal/status")
    assert status["needs_acceptance"] is False and status["upcoming_pending"] is True
    [doc] = [d for d in status["documents"] if d["document"] == "PRIVACY"]
    assert doc["upcoming"]["id"] == scheduled["id"] and doc["current"] is None

    status = await user.post("/legal/accept", {"version_ids": [scheduled["id"]]})
    assert status["upcoming_pending"] is False

    duplicate = await admin.request(
        "POST",
        "/admin/compliance/legal/versions",
        json={"document": "PRIVACY", "version": "2026-11", "summary": "The same label twice is refused."},
    )
    assert duplicate.status_code == 409
    past = await admin.request(
        "POST",
        "/admin/compliance/legal/versions",
        json={
            "document": "PRIVACY",
            "version": "2020-01",
            "summary": "A version cannot start in the past.",
            "effective_at": "2020-01-01T00:00:00Z",
        },
    )
    assert past.status_code == 422

    withdrawn = await admin.post(f"/admin/compliance/legal/versions/{scheduled['id']}/withdraw")
    assert withdrawn["withdrawn_at"]
    assert (await user.get("/legal/status"))["upcoming_pending"] is False

    live = await admin.post(
        "/admin/compliance/legal/versions",
        {"document": "PRIVACY", "version": "2026-12", "summary": "In effect immediately for this test."},
        expected=201,
    )
    refused = await admin.request("POST", f"/admin/compliance/legal/versions/{live['id']}/withdraw")
    assert refused.status_code == 409
    plain = await user.request(
        "POST",
        "/admin/compliance/legal/versions",
        json={"document": "TERMS", "version": "x1", "summary": "Ordinary users cannot publish."},
    )
    assert plain.status_code == 403
