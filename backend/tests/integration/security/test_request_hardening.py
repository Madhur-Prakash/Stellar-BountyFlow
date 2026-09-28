"""Request-level hardening: client IP derivation for rate limits, Argon2 off the event loop, body limits, content
types, URL scheme validation, and LIKE-pattern escaping."""

from __future__ import annotations

import threading
import uuid
from typing import Any

import pytest

from tests.integration.api.conftest import bounty_payload, register
from tests.integration.security.helpers import new_requester, new_user, published


def _registration(handle: str) -> dict[str, str]:
    return {
        "email": f"{handle}@example.com",
        "password": "Str0ng-passphrase!",
        "username": handle,
        "display_name": handle.title(),
    }


async def test_spoofed_forwarded_for_cannot_bypass_ip_rate_limit(client_factory: Any) -> None:
    """SEC-03: behind the reverse proxy the real client address is the entry the proxy appends (right-most).
    Rotating a client-supplied left-most X-Forwarded-For value must not create fresh rate-limit buckets."""
    client = client_factory()
    statuses = []
    for i in range(11):  # auth:register allows 10 per hour per client IP
        response = await client.request(
            "POST",
            "/auth/register",
            json=_registration(f"xff{i}_{uuid.uuid4().hex[:6]}"),
            headers={"X-Forwarded-For": f"10.9.8.{i}, 203.0.113.7"},
        )
        statuses.append(response.status_code)
        client.http.cookies.clear()
    assert statuses[:10] == [201] * 10
    assert statuses[10] == 429


async def test_oversized_forwarded_for_does_not_break_login(client_factory: Any) -> None:
    """SEC-03: the derived client IP is persisted on the session row (64 chars); an attacker-controlled header
    value must never turn registration/login into a 500."""
    client = client_factory()
    response = await client.request(
        "POST",
        "/auth/register",
        json=_registration(f"longxff_{uuid.uuid4().hex[:6]}"),
        headers={"X-Forwarded-For": "A" * 300},
    )
    assert response.status_code == 201, response.text


async def test_password_hashing_runs_off_the_event_loop(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-04: Argon2id (64 MiB, t=3) takes ~100 ms. Run inline it stalls every request served by the worker, so
    unauthenticated login/register traffic becomes a cheap denial of service. It must run in a worker thread."""
    import app.core.security as security
    import app.modules.auth.service as auth_service

    loop_thread = threading.get_ident()
    seen: list[bool] = []
    real_hash, real_verify = security.hash_password, security.verify_password

    def spy_hash(password: str) -> str:
        seen.append(threading.get_ident() == loop_thread)
        return real_hash(password)

    def spy_verify(password_hash: str, password: str) -> bool:
        seen.append(threading.get_ident() == loop_thread)
        return real_verify(password_hash, password)

    for module in (security, auth_service):
        monkeypatch.setattr(module, "hash_password", spy_hash, raising=False)
        monkeypatch.setattr(module, "verify_password", spy_verify, raising=False)

    client = client_factory()
    me = await register(client)
    client.http.cookies.clear()
    await client.post("/auth/login", {"email": me["email"], "password": "Str0ng-passphrase!"}, expected=200)
    await client.request(
        "POST", "/auth/login", json={"email": "nobody@example.com", "password": "whatever-1"}, expected=401
    )
    assert seen, "password hashing was not exercised"
    assert not any(seen), "Argon2 ran on the event-loop thread"


async def test_login_rejects_non_json_bodies(client_factory: Any) -> None:
    """Login/registration are CSRF-exempt; a cross-site HTML form can only send urlencoded, multipart or
    text/plain bodies, none of which may be accepted as JSON (login CSRF)."""
    client = client_factory()
    for content_type in ("text/plain", "application/x-www-form-urlencoded"):
        response = await client.request(
            "POST",
            "/auth/login",
            content=b'{"email": "a@example.com", "password": "Str0ng-passphrase!"}',
            headers={"Content-Type": content_type},
        )
        assert response.status_code == 422, (content_type, response.status_code)


async def test_request_body_size_limit(client_factory: Any) -> None:
    client = client_factory()
    response = await client.request(
        "POST", "/auth/login", content=b"x" * (1_048_576 + 10), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


BAD_URLS = [
    "javascript:alert(document.cookie)",
    "JaVaScRiPt:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "ftp://example.com/x",
]


@pytest.mark.parametrize("bad", BAD_URLS)
async def test_every_url_field_rejects_non_http_schemes(
    client_factory: Any, outbox_mail: Any, bad: str
) -> None:
    """Stored URLs are rendered as links/images by the SPA: only http(s) may ever be accepted."""
    requester, _wallet = await new_requester(client_factory, outbox_mail, "urls")
    for field in ("avatar_url", "portfolio_url", "github_url"):
        r = await requester.request("PATCH", "/users/me", json={field: bad})
        assert r.status_code == 422, (field, r.text)

    for payload in (
        bounty_payload(repository_url=bad),
        bounty_payload(links=[{"label": "spec", "url": bad}]),
    ):
        r = await requester.request("POST", "/bounties", json=payload)
        assert r.status_code == 422, r.text
    draft = await requester.post("/bounties", bounty_payload(), expected=201)
    for patch in ({"repository_url": bad}, {"links": [{"label": "spec", "url": bad}]}):
        r = await requester.request("PATCH", f"/bounties/{draft['id']}", json=patch)
        assert r.status_code == 422, r.text

    bounty = await published(requester)
    contributor = await new_user(client_factory, "urls_c")
    r = await contributor.request(
        "POST",
        f"/bounties/{bounty['id']}/applications",
        json={"cover_message": "A long enough cover message for validation.", "work_samples": [bad]},
    )
    assert r.status_code == 422, r.text
    # Submission / dispute schemas: validated before any ownership check, so any caller exercises them.
    for path, body in (
        (f"/bounties/{bounty['id']}/submissions", {"description": "x" * 30, "evidence_url": bad}),
        (f"/bounties/{bounty['id']}/submissions", {"description": "x" * 30, "evidence_links": [bad]}),
        (f"/bounties/{bounty['id']}/disputes", {"reason": "x" * 30, "evidence_url": bad}),
        (f"/submissions/{uuid.uuid4()}", {"evidence_url": bad}),
        (f"/disputes/{uuid.uuid4()}/evidence", {"description": "evidence", "url": bad}),
    ):
        method = "PATCH" if path.startswith("/submissions/") else "POST"
        r = await contributor.request(method, path, json=body)
        assert r.status_code == 422, (path, r.text)


async def test_marketplace_search_escapes_like_wildcards(client_factory: Any, outbox_mail: Any) -> None:
    """SEC-07: '%' and '_' in the free-text query are literals, not LIKE wildcards (no match-everything or
    pathological patterns)."""
    requester, _ = await new_requester(client_factory, outbox_mail, "like")
    await published(requester, title="Escrow status widget build")
    anon = client_factory()
    assert (await anon.get("/bounties"))["total"] == 1
    for q in ("%", "_", "%_%", "E%w"):
        assert (await anon.get("/bounties", params={"q": q}))["total"] == 0, q
    assert (await anon.get("/bounties", params={"q": "status widget"}))["total"] == 1


async def test_client_trace_ids_are_sanitised(client_factory: Any, db_session: Any) -> None:
    """Client-supplied X-Request-ID / X-Correlation-ID values flow into every log line, audit row and outbox
    event; malformed values (spaces, 'key=value', oversize) are replaced, never propagated."""
    from sqlalchemy import select

    from app.messaging.models import OutboxEvent

    forged = "evil user_id=00000000-0000-0000-0000-000000000000 level=CRITICAL"
    client = client_factory()
    response = await client.request(
        "POST",
        "/auth/register",
        json=_registration(f"trace_{uuid.uuid4().hex[:6]}"),
        headers={"X-Request-ID": forged, "X-Correlation-ID": forged + "x" * 500},
    )
    assert response.status_code == 201
    assert response.headers["X-Request-ID"] != forged
    payloads = (await db_session.scalars(select(OutboxEvent.payload))).all()
    assert payloads and all(
        p.get("correlation_id") in (None, response.headers["X-Request-ID"]) for p in payloads
    )

    ok = await client_factory().request(
        "GET", "/config/public", headers={"X-Request-ID": "req-0123456789abcdef"}
    )
    assert ok.headers["X-Request-ID"] == "req-0123456789abcdef"  # well-formed IDs are still honoured
