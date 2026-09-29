"""Authorization regression matrix, driven by the OpenAPI document so new routes are covered automatically.

* Every mutating route requires the CSRF double-submit header, except the explicit exempt list.
* Every route requires authentication, except the explicit public list.
* Every staff route rejects ordinary users.
* Object-level access (IDOR) for applications, submissions, disputes, notifications, wallets, sessions,
  transactions, payments, drafts and hidden bounties; role escalation; suspended accounts.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.modules.users.models import Role
from tests.integration.api.conftest import ApiClient, chain_action, drain_events, register, sign_xdr
from tests.integration.security.helpers import (
    assigned_contributor,
    funded,
    new_requester,
    new_user,
    published,
    set_role,
)

PREFIX = "/api/v1"
MUTATING = {"post", "put", "patch", "delete"}

CSRF_EXEMPT = {
    ("post", "/auth/register"),
    ("post", "/auth/login"),
    ("post", "/auth/refresh"),
    ("post", "/auth/forgot-password"),
    ("post", "/auth/reset-password"),
    ("post", "/auth/verify-email"),
    ("post", "/saved-searches/unsubscribe"),  # authorised by the signed token from the alert email
    ("post", "/credentials/verify"),  # public, cookie-free and side-effect free
    ("post", "/github/webhook"),  # server-to-server, authenticated by its HMAC-SHA256 signature
}

PUBLIC = CSRF_EXEMPT | {
    ("get", "/skills/related"),
    ("post", "/auth/logout"),
    ("get", "/config/public"),
    ("get", "/bounties"),
    ("get", "/bounties/featured"),
    ("get", "/bounties/{bounty_ref}"),
    ("get", "/bounties/{bounty_ref}/activity"),
    ("get", "/bounties/{bounty_id}/funding"),
    ("get", "/bounties/{bounty_id}/transactions"),
    ("get", "/transactions/{transaction_ref}"),
    ("get", "/users/{username}"),
    ("get", "/users/{username}/bounties"),
    ("get", "/users/{username}/contributions"),
    ("get", "/users/{username}/stats"),
    ("get", "/analytics/public"),
    ("get", "/legal/versions"),
    ("get", "/users/{username}/reputation"),
    ("get", "/users/{username}/attestations"),
    ("get", "/attestations/{attestation_ref}"),
    ("get", "/credentials/issuer"),
    ("get", "/credentials/status/revocation"),
    ("get", "/bounties/{bounty_ref}/questions"),
    ("get", "/github/config"),
    ("get", "/users/{username}/github"),
    ("get", "/escrow/config"),
    ("get", "/bounties/{bounty_id}/milestones"),
    ("get", "/assets"),  # the reward asset registry: shown on the marketplace filter to anyone
}

STAFF_ONLY_EXTRA = {
    ("get", "/analytics/platform"),
    ("post", "/bounties/{bounty_id}/feature"),
    ("post", "/disputes/{dispute_id}/assign"),
    ("post", "/disputes/{dispute_id}/resolve"),
}


def _operations(app: Any) -> list[tuple[str, str]]:
    ops = []
    for path, item in app.openapi()["paths"].items():
        if not path.startswith(PREFIX):
            continue
        for method in item:
            if method in {"get", "post", "put", "patch", "delete"}:
                ops.append((method, path[len(PREFIX) :]))
    return sorted(ops)


def _concrete(path: str) -> str:
    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        return "someone" if name == "username" else str(uuid.uuid4())

    return re.sub(r"\{([a-z_]+)\}", fill, path)


async def test_route_inventory_is_classified(app: Any) -> None:
    ops = set(_operations(app))
    assert ops, "OpenAPI exposes no routes"
    missing = (PUBLIC | STAFF_ONLY_EXTRA) - ops
    assert not missing, f"allowlists reference unknown routes: {sorted(missing)}"


async def test_every_mutating_route_requires_csrf(app: Any, client_factory: Any) -> None:
    client = client_factory()
    await register(client)  # authenticated: CSRF is the only thing missing
    for method, path in _operations(app):
        if method not in MUTATING:
            continue
        response = await client.request(method.upper(), _concrete(path), json={}, csrf=False)
        code = response.json().get("error", {}).get("code") if response.content else None
        if (method, path) in CSRF_EXEMPT:
            assert code != "csrf_failed", (method, path)
        else:
            assert response.status_code == 403 and code == "csrf_failed", (method, path, response.status_code)
            wrong = await client.request(
                method.upper(), _concrete(path), json={}, csrf=False, headers={"X-CSRF-Token": "forged"}
            )
            assert wrong.status_code == 403, (method, path)


async def test_every_non_public_route_requires_authentication(app: Any, client_factory: Any) -> None:
    anon = client_factory()
    anon.http.cookies.set("bf_csrf", "anon-token")  # satisfy CSRF so authentication is what is tested
    for method, path in _operations(app):
        if (method, path) in PUBLIC:
            continue
        response = await anon.request(method.upper(), _concrete(path), json={})
        assert response.status_code == 401, (method, path, response.status_code, response.text[:200])


async def test_staff_routes_reject_ordinary_users(app: Any, client_factory: Any) -> None:
    user = await new_user(client_factory, "plain")
    staff = {(m, p) for m, p in _operations(app) if p.startswith("/admin/")} | STAFF_ONLY_EXTRA
    for method, path in sorted(staff):
        body: dict[str, Any] = {}
        if path.endswith("/feature"):
            body = {"featured": True}
        elif path.endswith("/resolve") and path.startswith("/disputes"):
            body = {"resolution": "DISMISSED", "note": "ten characters at least"}
        elif path.endswith("/moderate"):
            body = {"action": "HIDE", "reason": "spam spam"}
        elif path.startswith("/admin/reports/"):
            body = {"status": "DISMISSED", "note": "n/a"}
        elif path.startswith("/admin/users/"):
            body = {"role": "ADMIN"}
        response = await user.request(method.upper(), _concrete(path), json=body)
        assert response.status_code == 403, (method, path, response.status_code)


async def test_idor_matrix(client_factory: Any, outbox_mail: Any, db_session: Any) -> None:
    requester, req_wallet = await new_requester(client_factory, outbox_mail, "owner")
    bounty = await funded(requester, req_wallet, reward_amount="6")
    bid = bounty["id"]
    contributor, _cw, accepted = await assigned_contributor(client_factory, requester, bid, "worker")
    app_id = accepted["id"]
    submission = await contributor.post(
        f"/bounties/{bid}/submissions",
        {"description": "Delivered everything described in the acceptance criteria."},
        expected=201,
    )
    dispute = await contributor.post(
        f"/bounties/{bid}/disputes", {"reason": "No review for a very long time, please help."}, expected=201
    )
    await drain_events()
    contributor_note = (await contributor.get("/notifications"))["items"][0]["id"]
    contributor_wallet_id = (await contributor.get("/wallets"))[0]["id"]
    contributor_session = (await contributor.get("/auth/sessions"))[0]["id"]
    spare = await published(requester, title="Spare bounty for an unsigned transaction")
    unsigned = await requester.post(
        f"/bounties/{spare['id']}/funding/prepare", {"wallet_address": req_wallet}
    )
    draft = await requester.post(
        "/bounties",
        {
            "title": "Secret draft bounty title",
            "short_description": "A short description that is long enough to pass.",
            "description": "A private draft description that nobody else should be able to read at all.",
            "category": "DEVELOPMENT",
            "difficulty": "BEGINNER",
            "reward_amount": "1",
        },
        expected=201,
    )

    outsider, out_wallet = await new_requester(client_factory, outbox_mail, "outsider")

    async def expect(client: ApiClient, method: str, path: str, codes: tuple[int, ...], **kw: Any) -> None:
        response = await client.request(method, path, **kw)
        assert response.status_code in codes, (method, path, response.status_code, response.text[:200])

    # Applications
    await expect(outsider, "GET", f"/bounties/{bid}/applications", (403,))
    await expect(contributor, "GET", f"/bounties/{bid}/applications", (403,))
    await expect(outsider, "POST", f"/applications/{app_id}/withdraw", (404,))
    await expect(outsider, "POST", f"/applications/{app_id}/accept", (403,), json={})
    await expect(outsider, "POST", f"/applications/{app_id}/reject", (403,), json={})
    mine = await contributor.get("/applications/me")
    assert mine["items"][0]["review_note"] is None  # the requester's private review note never leaks
    owner_view = await requester.get(f"/bounties/{bid}/applications")
    assert owner_view["items"][0]["review_note"] == "private note"

    # Submissions
    sid = submission["id"]
    await expect(outsider, "GET", f"/submissions/{sid}", (404,))
    await expect(outsider, "PATCH", f"/submissions/{sid}", (404,), json={"description": "x" * 30})
    for action, body in (
        ("approve", {}),
        ("reject", {"reason": "nope nope"}),
        ("request-revision", {"feedback": "more!"}),
    ):
        await expect(outsider, "POST", f"/submissions/{sid}/{action}", (403,), json=body)
        await expect(contributor, "POST", f"/submissions/{sid}/{action}", (403,), json=body)
    assert (await outsider.get(f"/bounties/{bid}/submissions"))["total"] == 0

    # Disputes
    did = dispute["id"]
    await expect(outsider, "GET", f"/disputes/{did}", (404,))
    await expect(outsider, "POST", f"/disputes/{did}/evidence", (404,), json={"description": "fake evidence"})
    assert await outsider.get("/disputes/me") == []

    # Notifications, wallets, sessions
    await expect(outsider, "POST", f"/notifications/{contributor_note}/read", (404,))
    assert all(n["id"] != contributor_note for n in (await outsider.get("/notifications"))["items"])
    await expect(outsider, "DELETE", f"/wallets/{contributor_wallet_id}", (404,))
    await expect(outsider, "DELETE", f"/auth/sessions/{contributor_session}", (404,))
    assert len(await contributor.get("/wallets")) == 1
    await contributor.get("/auth/me")  # session still alive

    # Transactions and payments
    tx_id = unsigned["transaction"]["id"]
    # Even with the owner's genuinely signed envelope (e.g. intercepted), another user cannot submit it.
    stolen = {"signed_xdr": sign_xdr(unsigned["unsigned_xdr"], req_wallet)}
    await expect(outsider, "POST", f"/transactions/{tx_id}/submit", (404,), json=stolen)
    await expect(outsider, "GET", f"/transactions/{tx_id}", (404,))
    await expect(client_factory(), "GET", f"/transactions/{tx_id}", (404,))
    assert (await outsider.get("/transactions/me"))["total"] == 0
    assert (await outsider.get("/payments/me", params={"direction": "sent"}))["total"] == 0

    # Someone else's bounty: no authoring, lifecycle or chain actions
    await expect(outsider, "PATCH", f"/bounties/{bid}", (403,), json={"title": "Hijacked bounty title"})
    await expect(outsider, "POST", f"/bounties/{bid}/publish", (403,))
    await expect(outsider, "POST", f"/bounties/{bid}/cancel", (403,), json={"reason": "because"})
    for action in ("FUND", "REQUEST_CANCEL", "REFUND"):
        await expect(
            outsider,
            "POST",
            f"/bounties/{bid}/chain/prepare",
            (403,),
            json={"action": action, "wallet_address": out_wallet},
        )
    await expect(
        outsider,
        "POST",
        f"/bounties/{bid}/chain/prepare",
        (403,),
        json={"action": "RESOLVE_DISPUTE", "wallet_address": out_wallet, "dispute_id": did},
    )
    # A verified wallet of *another* user cannot be used as the signing wallet.
    await expect(
        outsider,
        "POST",
        f"/bounties/{bid}/chain/prepare",
        (403,),
        json={"action": "FUND", "wallet_address": req_wallet},
    )

    # Drafts are invisible to everyone but the owner (and staff)
    draft_id = draft["id"]
    for path in (
        f"/bounties/{draft_id}",
        f"/bounties/{draft['slug']}",
        f"/bounties/{draft_id}/activity",
        f"/bounties/{draft_id}/funding",
        f"/bounties/{draft_id}/transactions",
    ):
        await expect(outsider, "GET", path, (404,))
        await expect(client_factory(), "GET", path, (404,))
    await expect(outsider, "POST", f"/bounties/{draft_id}/bookmark", (404,))
    await expect(
        outsider, "POST", f"/bounties/{draft_id}/report", (404,), json={"reason": "reporting a draft"}
    )

    # Hidden bounties disappear for the public but stay visible to the owner
    moderator = await new_user(client_factory, "mod")
    await set_role(db_session, moderator, Role.MODERATOR)
    other = await published(requester, title="Bounty that will be hidden")
    await moderator.post(f"/admin/bounties/{other['id']}/moderate", {"action": "HIDE", "reason": "spam spam"})
    await expect(outsider, "GET", f"/bounties/{other['id']}", (404,))
    await expect(client_factory(), "GET", f"/bounties/{other['id']}", (404,))
    assert all(b["id"] != other["id"] for b in (await client_factory().get("/bounties"))["items"])
    await requester.get(f"/bounties/{other['id']}")


async def test_role_escalation_is_impossible(client_factory: Any, db_session: Any) -> None:
    user = await new_user(client_factory, "climber")
    me = await user.patch("/users/me", {"bio": "hi", "role": "ADMIN", "permissions": ["user:manage"]})
    assert me["role"] == "USER" and "user:manage" not in me["permissions"]

    moderator = await new_user(client_factory, "mod2")
    await set_role(db_session, moderator, Role.MODERATOR)
    assert moderator.me is not None and user.me is not None
    for target in (moderator.me["id"], user.me["id"]):
        await moderator.request("PATCH", f"/admin/users/{target}", json={"role": "ADMIN"}, expected=403)
    await moderator.request("PATCH", f"/admin/users/{user.me['id']}", json={"is_active": False}, expected=403)

    admin = await new_user(client_factory, "admin2")
    await set_role(db_session, admin, Role.ADMIN)
    assert admin.me is not None
    await admin.request("PATCH", f"/admin/users/{admin.me['id']}", json={"role": "USER"}, expected=403)
    await admin.request("PATCH", f"/admin/users/{admin.me['id']}", json={"is_active": False}, expected=403)

    # Demotion takes effect immediately (permissions come from the DB, not from the JWT role claim).
    await admin.patch(f"/admin/users/{moderator.me['id']}", {"role": "USER"})
    await moderator.request("GET", "/admin/users", expected=403)


async def test_suspension_revokes_every_session(client_factory: Any, db_session: Any) -> None:
    victim = client_factory()
    me = await register(victim)
    admin = await new_user(client_factory, "admin3")
    await set_role(db_session, admin, Role.ADMIN)
    await admin.patch(f"/admin/users/{me['id']}", {"is_active": False})
    await victim.request("GET", "/auth/me", expected=(401, 403))
    await victim.request("POST", "/auth/refresh", expected=401)
    relogin = await client_factory().request(
        "POST", "/auth/login", json={"email": me["email"], "password": "Str0ng-passphrase!"}
    )
    assert relogin.status_code == 401 and relogin.json()["error"]["code"] == "account_suspended"
    await client_factory().request("GET", f"/users/{me['username']}", expected=404)


async def test_there_is_no_passwordless_login_route(app: Any) -> None:
    """Every account signs in with its own credentials; no shortcut login endpoint exists."""
    paths = app.openapi()["paths"]
    assert "/api/v1/auth/demo-login" not in paths
    assert not [p for p in paths if "demo" in p]


async def test_refresh_token_is_bound_to_its_session(client_factory: Any) -> None:
    """A refresh token is '<session_id>.<secret>'; swapping in another session id never works."""
    alice, bob = client_factory(), client_factory()
    await register(alice)
    await register(bob)
    a_sid, _ = alice.http.cookies.get("bf_refresh").split(".", 1)
    _, b_secret = bob.http.cookies.get("bf_refresh").split(".", 1)
    forged = client_factory()
    forged.http.cookies.set("bf_refresh", f"{a_sid}.{b_secret}", path="/api/v1/auth")
    await forged.request("POST", "/auth/refresh", expected=401)


async def test_unsigned_chain_actions_do_not_touch_funds(client_factory: Any, outbox_mail: Any) -> None:
    """Amounts and destinations come from server state: a client-supplied amount can never exceed what the bounty
    requires, and the payout destination is always the contributor's verified wallet."""
    requester, wallet = await new_requester(client_factory, outbox_mail, "amounts")
    bounty = await published(requester, reward_amount="5")
    over = await requester.request(
        "POST",
        f"/bounties/{bounty['id']}/funding/prepare",
        json={"wallet_address": wallet, "amount": "5.0000001"},
    )
    assert over.status_code == 422
    for bad in ("-1", "0", "1e3", "abc", "0.00000001"):
        r = await requester.request(
            "POST",
            f"/bounties/{bounty['id']}/funding/prepare",
            json={"wallet_address": wallet, "amount": bad},
        )
        assert r.status_code in (409, 422), (bad, r.status_code)
    tx = await chain_action(
        requester, f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet}
    )
    assert tx["amount"] == "5.0000000"
