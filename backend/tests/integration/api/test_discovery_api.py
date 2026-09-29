"""Saved searches (matching, instant alerts, digests, unsubscribe) and skill-graph recommendations over the API."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.discovery.models import MatchDelivery, SavedSearchMatch
from app.modules.discovery.saved_searches import match_bounty
from app.modules.users.models import Role
from tests.integration.api.conftest import ApiClient, bounty_payload, drain_events, register, verify_email
from tests.integration.security.helpers import set_role

UNSUBSCRIBE_RE = re.compile(r"/saved-searches/unsubscribe\?token=([A-Za-z0-9_\-.]+)")


async def _verified(client_factory: Any, mail: Any, name: str) -> ApiClient:
    client = client_factory()
    await register(client, f"{name}_{uuid.uuid4().hex[:6]}")
    await verify_email(client, mail)
    return client


async def _published(client: ApiClient, **overrides: Any) -> dict[str, Any]:
    bounty = await client.post("/bounties", bounty_payload(**{"tags": [], **overrides}), expected=201)
    return await client.post(f"/bounties/{bounty['id']}/publish")


def _mail_to(mail: Any, client: ApiClient, subject: str) -> list[Any]:
    assert client.me is not None
    return [m for m in mail.sent if m.to == client.me["email"] and subject in m.subject]


async def _saved_notes(client: ApiClient) -> list[dict[str, Any]]:
    page = await client.get("/notifications")
    return [n for n in page["items"] if n["notification_type"] == "SAVED_SEARCH_MATCH"]


async def test_saved_search_crud_limits_and_ownership(client_factory: Any, outbox_mail: Any) -> None:
    owner = client_factory()
    await register(owner, f"ss_owner_{uuid.uuid4().hex[:6]}")
    created = await owner.post(
        "/saved-searches",
        {
            "name": "  Rust   security work ",
            "filters": {
                "q": "audit",
                "category": ["SECURITY"],
                "skills": ["Rust"],
                "min_reward": "50",
                "deadline_within_days": 7,
                "funded_only": True,
                "sort": "reward_high",
            },
            "alert_frequency": "DAILY",
            "notify_email": False,
        },
        expected=201,
    )
    assert created["name"] == "Rust security work"
    assert created["filters"]["skills"] == ["rust"] and created["filters"]["deadline_within_days"] == 7
    assert created["filters"]["sort"] == "reward_high"
    assert created["alert_frequency"] == "DAILY" and created["next_digest_at"] is not None
    assert created["notify_in_app"] is True and created["notify_email"] is False and created["new_count"] == 0

    fixed = await owner.request(
        "POST", "/saved-searches", json={"name": "x", "filters": {"deadline_before": "2030-01-01T00:00:00Z"}}
    )
    assert fixed.status_code == 422

    sid = created["id"]
    updated = await owner.patch(
        f"/saved-searches/{sid}", {"name": "Audits", "alert_frequency": "INSTANT", "is_paused": True}
    )
    assert updated["name"] == "Audits" and updated["is_paused"] is True and updated["next_digest_at"] is None

    stranger = client_factory()
    await register(stranger)
    await stranger.request("GET", f"/saved-searches/{sid}", expected=404)
    await stranger.request("PATCH", f"/saved-searches/{sid}", json={"name": "mine"}, expected=404)
    await stranger.request("DELETE", f"/saved-searches/{sid}", expected=404)
    assert await stranger.get("/saved-searches") == []

    for i in range(24):
        await owner.post("/saved-searches", {"name": f"Search {i}"}, expected=201)
    full = await owner.request("POST", "/saved-searches", json={"name": "One too many"})
    assert full.status_code == 409

    await owner.request("DELETE", f"/saved-searches/{sid}", expected=204)
    assert len(await owner.get("/saved-searches")) == 24


async def test_instant_alerts_match_like_the_marketplace(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    requester = await _verified(client_factory, outbox_mail, "ss_req")
    seeker = await _verified(client_factory, outbox_mail, "ss_seek")
    search = await seeker.post(
        "/saved-searches",
        {
            "name": "Vesting audits",
            "filters": {"q": "vesting", "category": ["SECURITY"], "skills": ["rust"]},
            "alert_frequency": "INSTANT",
        },
        expected=201,
    )
    # The requester's own catch-all search never alerts on their own bounties.
    await requester.post("/saved-searches", {"name": "Everything"}, expected=201)

    match = await _published(
        requester,
        title="Audit a vesting contract on Soroban",
        category="SECURITY",
        required_skills=["rust", "soroban"],
    )
    marketplace = await client_factory().get("/bounties?q=vesting&category=SECURITY&skills=rust")
    assert [b["id"] for b in marketplace["items"]] == [match["id"]]  # the same query in the marketplace
    await _published(
        requester, title="Design a vesting dashboard", category="DESIGN", required_skills=["figma"]
    )
    await _published(
        requester, title="Audit a lending contract", category="SECURITY", required_skills=["rust"]
    )
    await drain_events()

    notes = await _saved_notes(seeker)
    assert len(notes) == 1
    assert match["title"] in notes[0]["message"] and "Vesting audits" in notes[0]["message"]
    assert notes[0]["link"] == f"/bounties/{match['slug']}"
    assert await _saved_notes(requester) == []

    alerts = _mail_to(outbox_mail, seeker, "New bounty for your saved search")
    assert len(alerts) == 1
    assert match["title"] in alerts[0].text and "unsubscribe" in alerts[0].html.lower()
    assert (
        alerts[0].headers["List-Unsubscribe"].startswith("<http://frontend.test/saved-searches/unsubscribe?")
    )
    assert _mail_to(outbox_mail, requester, "New bounty for your saved search") == []
    # Choosing email for the search switched saved-search emails on in the seeker's settings.
    prefs = await seeker.get("/notification-preferences")
    assert prefs["types"]["SAVED_SEARCH_MATCH"] == {"in_app": True, "email": True}

    listed = await seeker.get("/saved-searches")
    assert listed[0]["new_count"] == 1
    viewed = await seeker.post(f"/saved-searches/{search['id']}/viewed")
    assert viewed["new_count"] == 0
    assert (await seeker.get(f"/saved-searches/{search['id']}"))["new_count"] == 0

    # A bounty matches a search once: a later event (e.g. funding) never alerts again.
    again = await match_bounty(
        db_session, uuid.UUID(match["id"]), trigger_event="bounty.funded", source_event_id=uuid.uuid4()
    )
    await db_session.commit()
    assert again == []

    # Unsubscribing from the email link needs no session and turns only this search's alerts off.
    token_match = UNSUBSCRIBE_RE.search(alerts[0].text)
    assert token_match is not None
    anon = client_factory()
    bad = await anon.request(
        "POST", "/saved-searches/unsubscribe", json={"token": token_match.group(1) + "x"}
    )
    assert bad.status_code == 422
    done = await anon.post("/saved-searches/unsubscribe", {"token": token_match.group(1)}, csrf=False)
    assert done == {"saved_search_id": search["id"], "name": "Vesting audits", "alert_frequency": "OFF"}

    later = await _published(
        requester, title="Review vesting maths in Soroban", category="SECURITY", required_skills=["rust"]
    )
    await drain_events()
    assert len(await _saved_notes(seeker)) == 1
    assert len(_mail_to(outbox_mail, seeker, "New bounty for your saved search")) == 1
    row = await db_session.scalar(
        select(SavedSearchMatch).where(SavedSearchMatch.bounty_id == uuid.UUID(later["id"]))
    )
    assert row is not None and row.delivery == MatchDelivery.SKIPPED  # still counted as new, not alerted
    assert (await seeker.get(f"/saved-searches/{search['id']}"))["new_count"] == 1


async def test_digests_collect_pending_matches(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    requester = await _verified(client_factory, outbox_mail, "dg_req")
    seeker = await _verified(client_factory, outbox_mail, "dg_seek")
    admin = client_factory()
    await register(admin, f"dg_admin_{uuid.uuid4().hex[:6]}")
    await set_role(db_session, admin, Role.ADMIN)
    await seeker.post(
        "/saved-searches",
        {"name": "Kafka docs", "filters": {"skills": ["kafka"]}, "alert_frequency": "DAILY"},
        expected=201,
    )
    first = await _published(
        requester, title="Document the Kafka consumer", required_skills=["kafka", "python"]
    )
    second = await _published(requester, title="Write a Kafka retry guide", required_skills=["kafka"])
    await drain_events()
    assert _mail_to(outbox_mail, seeker, "digest") == []  # nothing is sent before the digest
    assert await _saved_notes(seeker) == []

    disabled = await admin.request("POST", "/admin/discovery/digests/run", json={"frequency": "DAILY"})
    assert disabled.status_code == 404  # the trigger does not exist unless explicitly enabled

    monkeypatch.setenv("DISCOVERY_DIGEST_TRIGGER_ENABLED", "true")
    get_settings.cache_clear()
    plain = await seeker.request("POST", "/admin/discovery/digests/run", json={"frequency": "DAILY"})
    assert plain.status_code == 403
    result = await admin.post("/admin/discovery/digests/run", {"frequency": "DAILY"})
    assert result == {"frequency": "DAILY", "users": 1, "searches": 1, "matches": 2}
    await drain_events()

    digests = _mail_to(outbox_mail, seeker, "Your daily bounty digest")
    assert len(digests) == 1
    assert first["title"] in digests[0].text and second["title"] in digests[0].text
    assert UNSUBSCRIBE_RE.search(digests[0].text)
    notes = await _saved_notes(seeker)
    assert len(notes) == 1 and notes[0]["title"] == "New bounties match your saved searches"
    assert "2 new bounties" in notes[0]["message"]

    again = await admin.post("/admin/discovery/digests/run", {"frequency": "DAILY"})
    assert again["matches"] == 0  # every match is delivered once
    await drain_events()
    assert len(_mail_to(outbox_mail, seeker, "Your daily bounty digest")) == 1


async def test_recommendations_rank_by_skill_graph(client_factory: Any, outbox_mail: Any) -> None:
    requester = await _verified(client_factory, outbox_mail, "rc_req")
    contributor = await _verified(client_factory, outbox_mail, "rc_con")
    await contributor.patch("/users/me", {"skills": ["Rust", "soroban"]})

    exact = await _published(requester, title="Soroban escrow in Rust", required_skills=["rust", "soroban"])
    partial = await _published(requester, title="Rust CLI for payouts", required_skills=["rust", "cli"])
    unrelated = await _published(requester, title="Design the onboarding flow", required_skills=["figma"])
    applied = await _published(requester, title="Rust indexer for events", required_skills=["rust"])
    related_only = await _published(
        requester, title="WebAssembly size budget review", required_skills=["wasm"], tags=["performance"]
    )
    # Teach the graph that wasm goes with soroban work.
    for i in range(3):
        await _published(
            requester, title=f"Soroban wasm optimisation {i}", required_skills=["soroban", "wasm"]
        )
    own = await _published(contributor, title="My own Rust bounty here", required_skills=["rust"])
    await contributor.post(
        f"/bounties/{applied['id']}/applications",
        {"cover_message": "I have built several Rust indexers in production."},
        expected=201,
    )

    recs = await contributor.get("/recommendations")
    ids = [r["bounty"]["id"] for r in recs["items"]]
    assert recs["has_profile_skills"] is True and recs["seed_skills"][:2] == ["rust", "soroban"]
    assert ids[0] == exact["id"]
    assert partial["id"] in ids and related_only["id"] in ids
    assert unrelated["id"] not in ids and applied["id"] not in ids and own["id"] not in ids
    by_id = {r["bounty"]["id"]: r for r in recs["items"]}
    assert by_id[exact["id"]]["reason"]["matched_skills"] == ["rust", "soroban"]
    assert by_id[related_only["id"]]["reason"]["matched_skills"] == []
    assert by_id[related_only["id"]]["reason"]["related_skills"][0] == {
        "skill": "webassembly",
        "via": "soroban",
    }
    assert by_id[exact["id"]]["score"] > by_id[partial["id"]]["score"]

    narrowed = await contributor.get("/recommendations?q=CLI")
    assert [r["bounty"]["id"] for r in narrowed["items"]] == [partial["id"]]  # marketplace filters apply
    paged = await contributor.get("/recommendations?page=2&page_size=1")
    assert paged["total"] == recs["total"] and len(paged["items"]) == 1

    dashboard = await contributor.get("/dashboard")
    assert dashboard["recommendations"][0]["id"] == exact["id"]
    assert dashboard["recommendation_reasons"][exact["id"]]["matched_skills"] == ["rust", "soroban"]

    related = await client_factory().get("/skills/related?skills=soroban")
    assert related["skills"] == ["soroban"]
    wasm = next(r for r in related["related"] if r["skill"] == "webassembly")
    assert wasm["via"] == ["soroban"] and wasm["marketplace_skills"] == ["wasm"]

    newcomer = client_factory()
    await register(newcomer)
    empty = await newcomer.get("/recommendations")
    assert empty["items"] == [] and empty["has_profile_skills"] is False
    assert (await newcomer.get("/dashboard"))["recommendations"] == []
