"""Registration, login, CSRF, refresh-token rotation, email verification, password reset, profiles."""

from __future__ import annotations

from typing import Any

from tests.integration.api.conftest import drain_events, extract_token, register


async def test_register_login_me_and_logout(client_factory: Any) -> None:
    client = client_factory()
    me = await register(client, "alice_one")
    assert me["username"] == "alice_one"
    assert me["email_verified"] is False
    assert "bounty:create" in me["permissions"] and "bounty:moderate" not in me["permissions"]
    assert client.http.cookies.get("bf_access") and client.http.cookies.get("bf_csrf")

    assert (await client.get("/auth/me"))["id"] == me["id"]
    await client.post("/auth/logout", expected=204)
    await client.request("GET", "/auth/me", expected=401)

    other = client_factory()
    await other.post(
        "/auth/login", {"email": "alice_one@example.com", "password": "wrong-password-1"}, expected=401
    )
    logged_in = await other.post(
        "/auth/login", {"email": "ALICE_one@example.com", "password": "Str0ng-passphrase!"}
    )
    assert logged_in["id"] == me["id"]


async def test_register_validation_and_duplicates(client_factory: Any) -> None:
    client = client_factory()
    bad = await client.request(
        "POST",
        "/auth/register",
        json={"email": "not-an-email", "password": "short", "username": "X!", "display_name": ""},
    )
    assert bad.status_code == 422
    fields = {d["field"] for d in bad.json()["error"]["details"]}
    assert {"email", "password", "username"} <= fields
    await register(client, "dupe_user")
    again = client_factory()
    dup = await again.request(
        "POST",
        "/auth/register",
        json={
            "email": "dupe_user@example.com",
            "password": "Str0ng-passphrase!",
            "username": "someone_else",
            "display_name": "Someone",
        },
    )
    assert dup.status_code == 409


async def test_mutations_require_csrf_header(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    response = await client.request("PATCH", "/users/me", json={"bio": "hello"}, csrf=False)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
    ok = await client.patch("/users/me", {"bio": "hello"})
    assert ok["bio"] == "hello"


async def test_refresh_rotation_and_reuse_detection(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    old_refresh = client.http.cookies.get("bf_refresh")
    await client.post("/auth/refresh")
    new_refresh = client.http.cookies.get("bf_refresh")
    assert new_refresh and new_refresh != old_refresh

    # Replaying the rotated-away token is treated as theft: it fails and kills the session.
    attacker = client_factory()
    attacker.http.cookies.set("bf_refresh", old_refresh, path="/api/v1/auth")
    replay = await attacker.request("POST", "/auth/refresh")
    assert replay.status_code == 401
    victim = await client.request("POST", "/auth/refresh")
    assert victim.status_code == 401


async def test_email_verification_via_worker_email(client_factory: Any, outbox_mail: Any) -> None:
    client = client_factory()
    await register(client, "verify_me")
    await drain_events()
    token = extract_token(outbox_mail, "/verify-email")
    me = await client.post("/auth/verify-email", {"token": token})
    assert me["email_verified"] is True and me["onboarding"]["email_verified"] is True
    reuse = await client.request("POST", "/auth/verify-email", json={"token": token})
    assert reuse.status_code == 422


async def test_password_reset_is_generic_and_revokes_sessions(client_factory: Any, outbox_mail: Any) -> None:
    client = client_factory()
    await register(client, "reset_me")
    anon = client_factory()
    unknown = await anon.post("/auth/forgot-password", {"email": "nobody@example.com"})
    known = await anon.post("/auth/forgot-password", {"email": "reset_me@example.com"})
    assert unknown == known  # no account enumeration
    await drain_events()
    token = extract_token(outbox_mail, "/reset-password")
    await anon.post(
        "/auth/reset-password", {"token": token, "password": "N3w-strong-passphrase"}, expected=204
    )
    await client.request("GET", "/auth/me", expected=401)  # existing session revoked
    await anon.post("/auth/login", {"email": "reset_me@example.com", "password": "N3w-strong-passphrase"})


async def test_profile_update_and_public_profile(client_factory: Any) -> None:
    client = client_factory()
    await register(client, "profile_user")
    me = await client.patch(
        "/users/me",
        {
            "display_name": "Profile User",
            "bio": "I build things.",
            "skills": ["React", "Rust", "react"],
            "github_url": "https://github.com/profile-user",
            "wants_to_contribute": True,
        },
    )
    assert me["skills"] == ["react", "rust"]
    assert me["onboarding"]["profile_completed"] is True and me["onboarding"]["role_selected"] is True
    public = await client_factory().get("/users/profile_user")
    assert public["display_name"] == "Profile User" and public["stats"]["bounties_created"] == 0
    bad = await client.request("PATCH", "/users/me", json={"github_url": "https://evil.example.com/x"})
    assert bad.status_code == 422
    other = client_factory()
    await register(other, "taken_name")
    conflict = await client.request("PATCH", "/users/me", json={"username": "taken_name"})
    assert conflict.status_code == 409


async def test_wallet_link_is_single_use_and_signature_bound(client_factory: Any) -> None:
    from stellar_sdk import Keypair

    from tests.integration.api.conftest import KEYRING, sign_xdr

    client = client_factory()
    await register(client)
    kp = Keypair.random()
    KEYRING[kp.public_key] = kp
    challenge = await client.post("/wallets/challenge", {"public_address": kp.public_key})
    signed = sign_xdr(challenge["challenge_xdr"], kp.public_key)
    wallet = await client.post(
        "/wallets/verify", {"public_address": kp.public_key, "signed_challenge_xdr": signed}
    )
    assert wallet["network"] == "testnet"
    assert wallet["verification_status"] == "VERIFIED"
    replay = await client.request(
        "POST", "/wallets/verify", json={"public_address": kp.public_key, "signed_challenge_xdr": signed}
    )
    assert replay.status_code == 422  # challenges are single-use
    assert len(await client.get("/wallets")) == 1
    bad = await client.request("POST", "/wallets/challenge", json={"public_address": "G" + "A" * 55})
    assert bad.status_code == 422
    marker = await client.request(
        "POST", "/wallets/verify", json={"public_address": kp.public_key, "signed_challenge_xdr": "SIMULATED"}
    )
    assert marker.status_code == 422  # only real signatures prove ownership


async def test_real_signature_wallet_verification(client_factory: Any) -> None:
    """A signature from any key other than the claimed address is rejected."""
    from stellar_sdk import Keypair, TransactionEnvelope

    from app.blockchain.config import get_network

    client = client_factory()
    await register(client)
    kp = Keypair.random()
    challenge = await client.post("/wallets/challenge", {"public_address": kp.public_key})
    envelope = TransactionEnvelope.from_xdr(challenge["challenge_xdr"], get_network().passphrase)
    wrong = Keypair.random()
    envelope.sign(wrong)
    rejected = await client.request(
        "POST",
        "/wallets/verify",
        json={"public_address": kp.public_key, "signed_challenge_xdr": envelope.to_xdr()},
    )
    assert rejected.status_code == 422
    challenge = await client.post("/wallets/challenge", {"public_address": kp.public_key})
    envelope = TransactionEnvelope.from_xdr(challenge["challenge_xdr"], get_network().passphrase)
    envelope.sign(kp)
    wallet = await client.post(
        "/wallets/verify", {"public_address": kp.public_key, "signed_challenge_xdr": envelope.to_xdr()}
    )
    assert wallet["verification_status"] == "VERIFIED"


async def test_login_and_forgot_accept_special_use_domains(client_factory: Any) -> None:
    """Seeded accounts use reserved `*.test` addresses: login/forgot-password only look the email up, so they must
    reach the credential check (401 / generic 202) instead of failing strict email validation (422)."""
    client = client_factory()
    await client.post(
        "/auth/login",
        {"email": "ada.okafor@bountyflow.test", "password": "wrong-password-1"},
        expected=401,
    )
    await client.post("/auth/forgot-password", {"email": "someone@bountyflow.test"}, expected=202)
