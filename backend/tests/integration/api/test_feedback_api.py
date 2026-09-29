"""Feedback end to end: a signed-out visitor sends a note, a signed-in one is recognised, the captured context
is stored, the rate limit holds, and staff read and triage the queue behind ``feedback:review``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AuditLog
from app.modules.feedback.models import Feedback
from app.modules.users.models import Role
from tests.integration.api.conftest import ApiClient, register
from tests.integration.security.helpers import new_user, set_role

NOTE = {
    "kind": "BUG",
    "message": "The funding progress bar stays at zero after the escrow confirms.",
    "path": "/bounties/escrow-widget",
    "viewport_width": 1280,
    "viewport_height": 800,
}


async def staff(client_factory: Any, db_session: AsyncSession, name: str) -> ApiClient:
    client = await new_user(client_factory, name)
    await set_role(db_session, client, Role.MODERATOR)
    return client


async def test_a_visitor_gets_a_csrf_token_from_a_safe_request(client_factory: Any) -> None:
    """The form is open to people who never sign in, so the double-submit token cannot come from a login."""
    anon = client_factory()
    assert anon.http.cookies.get("bf_csrf") is None
    await anon.get("/config/public")
    assert anon.http.cookies.get("bf_csrf")

    # The token is still required: the same request without the header is refused.
    refused = await anon.request("POST", "/feedback", json=NOTE, csrf=False)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "csrf_failed"


async def test_anonymous_feedback_is_stored_with_its_context(
    client_factory: Any, db_session: AsyncSession
) -> None:
    anon = client_factory()
    await anon.get("/config/public")  # mints the CSRF token
    received = await anon.post(
        "/feedback",
        {**NOTE, "email": "Visitor@example.com", "message": f"  {NOTE['message']}  "},
        expected=201,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh) Chrome/141.0"},
    )

    row = await db_session.get(Feedback, received["id"])
    assert row is not None
    assert row.user_id is None and row.email == "Visitor@example.com"
    assert row.message == NOTE["message"]  # trimmed
    assert row.path == "/bounties/escrow-widget"
    assert (row.viewport_width, row.viewport_height) == (1280, 800)
    assert row.user_agent == "Mozilla/5.0 (Macintosh) Chrome/141.0"
    assert row.status.value == "NEW"


async def test_a_query_string_never_reaches_the_row(client_factory: Any, db_session: AsyncSession) -> None:
    """Only the route is kept: a query string can carry what someone typed into a search box."""
    anon = client_factory()
    await anon.get("/config/public")
    received = await anon.post(
        "/feedback", {**NOTE, "path": "/bounties?q=my+private+search#results"}, expected=201
    )
    row = await db_session.get(Feedback, received["id"])
    assert row is not None and row.path == "/bounties"

    off_site = await anon.post("/feedback", {**NOTE, "path": "https://example.com/phish"}, expected=201)
    row = await db_session.get(Feedback, off_site["id"])
    assert row is not None and row.path is None


async def test_a_signed_in_sender_is_recorded_and_the_form_email_is_ignored(
    client_factory: Any, db_session: AsyncSession
) -> None:
    client = client_factory()
    me = await register(client, "feedback_sender")
    received = await client.post(
        "/feedback", {**NOTE, "kind": "IDEA", "email": "someone-else@example.com"}, expected=201
    )
    row = await db_session.get(Feedback, received["id"])
    assert row is not None
    assert str(row.user_id) == me["id"]
    assert row.email is None  # the account's address is the reply address


async def test_message_bounds_and_kind_are_enforced(client_factory: Any) -> None:
    anon = client_factory()
    await anon.get("/config/public")
    for message in ("too short", "x" * 2001):
        await anon.request("POST", "/feedback", json={**NOTE, "message": message}, expected=422)
    await anon.request("POST", "/feedback", json={**NOTE, "kind": "RANT"}, expected=422)
    await anon.request("POST", "/feedback", json={**NOTE, "email": "not-an-address"}, expected=422)


async def test_submissions_are_rate_limited_per_ip(client_factory: Any) -> None:
    anon = client_factory()
    await anon.get("/config/public")
    for _ in range(5):
        await anon.post("/feedback", NOTE, expected=201)
    limited = await anon.request("POST", "/feedback", json=NOTE)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"


async def test_staff_read_filter_and_handle_the_queue(client_factory: Any, db_session: AsyncSession) -> None:
    sender = client_factory()
    await register(sender, "feedback_author")
    bug = await sender.post("/feedback", NOTE, expected=201)
    await sender.post("/feedback", {**NOTE, "kind": "PRAISE"}, expected=201)

    ordinary = await new_user(client_factory, "feedback_nosy")
    await ordinary.request("GET", "/admin/feedback", expected=403)
    await ordinary.request("POST", f"/admin/feedback/{bug['id']}/handle", json={}, expected=403)

    moderator = await staff(client_factory, db_session, "feedback_mod")
    page = await moderator.get("/admin/feedback")
    assert page["total"] == 2 and page["new_count"] == 2
    newest = page["items"][0]
    assert newest["sender"]["username"].startswith("feedback_author")
    assert newest["email"] is None and newest["user_agent"]

    only_bugs = await moderator.get("/admin/feedback", params={"kind": "BUG"})
    assert only_bugs["total"] == 1 and only_bugs["new_count"] == 2  # the waiting count ignores the filter

    handled = await moderator.post(
        f"/admin/feedback/{bug['id']}/handle", {"handled": True, "note": "Fixed in the escrow view."}
    )
    assert handled["status"] == "HANDLED" and handled["handled_note"] == "Fixed in the escrow view."
    assert handled["handled_by"]["username"].startswith("feedback_mod")

    after = await moderator.get("/admin/feedback", params={"status": "NEW"})
    assert after["total"] == 1 and after["new_count"] == 1

    reopened = await moderator.post(f"/admin/feedback/{bug['id']}/handle", {"handled": False})
    assert reopened["status"] == "NEW" and reopened["handled_at"] is None
    assert reopened["handled_by"] is None and reopened["handled_note"] is None

    actions = (
        await db_session.scalars(
            select(AuditLog.action).where(AuditLog.entity_type == "feedback").order_by(AuditLog.created_at)
        )
    ).all()
    assert list(actions) == ["feedback.handled", "feedback.reopened"]


async def test_handling_something_that_is_not_there_is_a_404(
    client_factory: Any, db_session: AsyncSession
) -> None:
    moderator = await staff(client_factory, db_session, "feedback_mod2")
    await moderator.request(
        "POST",
        "/admin/feedback/00000000-0000-0000-0000-000000000000/handle",
        json={"handled": True},
        expected=404,
    )
