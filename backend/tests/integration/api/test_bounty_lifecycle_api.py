"""Bounty CRUD, marketplace search, the full funded lifecycle, cancellation/refund, disputes, RBAC, notifications."""

from __future__ import annotations

import asyncio
from typing import Any

from tests.integration.api.conftest import (
    ApiClient,
    bounty_payload,
    chain_action,
    drain_events,
    link_wallet,
    register,
    verify_email,
)


async def _requester(client_factory: Any, mail: Any, name: str = "req") -> tuple[ApiClient, str]:
    client = client_factory()
    await register(client, f"{name}_{id(client) % 100000}")
    await verify_email(client, mail)
    wallet = await link_wallet(client)
    return client, wallet


async def _published(client: ApiClient, **overrides: Any) -> dict[str, Any]:
    bounty = await client.post("/bounties", bounty_payload(**overrides), expected=201)
    return await client.post(f"/bounties/{bounty['id']}/publish")


async def _funded(client: ApiClient, wallet: str, **overrides: Any) -> dict[str, Any]:
    bounty = await _published(client, **overrides)
    await chain_action(client, f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    return await client.get(f"/bounties/{bounty['id']}")


async def test_bounty_crud_visibility_and_validation(client_factory: Any, outbox_mail: Any) -> None:
    owner = client_factory()
    await register(owner, "crud_owner")
    invalid = await owner.request(
        "POST", "/bounties", json=bounty_payload(reward_amount="1.123456789", title="x")
    )
    assert invalid.status_code == 422
    draft = await owner.post("/bounties", bounty_payload(), expected=201)
    assert draft["status"] == "DRAFT" and draft["funding_status"] == "UNFUNDED"
    assert draft["reward_amount"] == "25.5000000" and draft["total_reward"] == "25.5000000"

    anon = client_factory()
    await anon.request("GET", f"/bounties/{draft['id']}", expected=404)  # drafts are private

    unverified = await owner.request("POST", f"/bounties/{draft['id']}/publish")
    assert unverified.status_code == 403 and unverified.json()["error"]["code"] == "email_not_verified"

    await verify_email(owner, outbox_mail)
    updated = await owner.patch(f"/bounties/{draft['id']}", {"reward_amount": "30", "positions_available": 2})
    assert updated["total_reward"] == "60.0000000"
    published = await owner.post(f"/bounties/{draft['id']}/publish")
    assert published["status"] == "OPEN" and published["published_at"]
    locked = await owner.request("PATCH", f"/bounties/{draft['id']}", json={"reward_amount": "10"})
    assert locked.status_code == 409  # money fields frozen after publishing

    by_slug = await anon.get(f"/bounties/{published['slug']}")
    assert by_slug["id"] == draft["id"] and by_slug["viewer"] is None

    stranger = client_factory()
    await register(stranger)
    forbidden = await stranger.request(
        "PATCH", f"/bounties/{draft['id']}", json={"title": "Hijacked title here"}
    )
    assert forbidden.status_code == 403


async def test_marketplace_search_filters_sort_and_bookmarks(client_factory: Any, outbox_mail: Any) -> None:
    owner = client_factory()
    await register(owner, "market_owner")
    await verify_email(owner, outbox_mail)
    await _published(
        owner,
        title="Soroban escrow security audit",
        category="SECURITY",
        reward_amount="500",
        required_skills=["rust", "soroban"],
        difficulty="EXPERT",
    )
    await _published(
        owner,
        title="Landing page illustration set",
        category="DESIGN",
        reward_amount="40",
        required_skills=["figma"],
        difficulty="BEGINNER",
        description="Create a consistent illustration set for our landing page with clear specs.",
    )
    anon = client_factory()
    everything = await anon.get("/bounties")
    assert everything["total"] == 2
    search = await anon.get("/bounties", params={"q": "escrow audit"})
    assert [b["title"] for b in search["items"]] == ["Soroban escrow security audit"]
    assert (await anon.get("/bounties", params={"category": "DESIGN"}))["total"] == 1
    assert (await anon.get("/bounties", params={"skills": "rust,go"}))["total"] == 1
    assert (await anon.get("/bounties", params={"min_reward": "100"}))["total"] == 1
    assert (await anon.get("/bounties", params={"funded_only": "true"}))["total"] == 0
    ordered = await anon.get("/bounties", params={"sort": "reward_low"})
    assert [b["reward_amount"] for b in ordered["items"]] == ["40.0000000", "500.0000000"]
    page = await anon.get("/bounties", params={"page_size": 1, "page": 2})
    assert page["pages"] == 2 and len(page["items"]) == 1
    bad = await anon.request("GET", "/bounties", params={"category": "NOPE"})
    assert bad.status_code == 422

    fan = client_factory()
    await register(fan)
    target = search["items"][0]["id"]
    await fan.post(f"/bounties/{target}/bookmark", expected=204)
    await fan.post(f"/bounties/{target}/bookmark", expected=204)  # idempotent
    saved = await fan.get("/bounties/saved")
    assert saved["total"] == 1 and saved["items"][0]["is_bookmarked"] is True
    await fan.request("DELETE", f"/bounties/{target}/bookmark", expected=204)
    assert (await fan.get("/bounties/saved"))["total"] == 0


async def test_full_lifecycle_with_onchain_escrow(client_factory: Any, outbox_mail: Any) -> None:
    requester, req_wallet = await _requester(client_factory, outbox_mail, "life")
    bounty = await _funded(requester, req_wallet, reward_amount="12.5")
    assert bounty["status"] == "FUNDED" and bounty["funding_status"] == "FUNDED"
    assert bounty["escrow"]["funded_amount"] == "12.5000000"
    assert bounty["escrow"]["contract_id"] == "CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY"
    assert bounty["escrow"]["explorer_url"].endswith(
        "/contract/CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY"
    )
    bid = bounty["id"]

    contributor = client_factory()
    await register(contributor, "life_contrib")
    app = await contributor.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "I have built several escrow widgets before and can start now."},
        expected=201,
    )
    dup = await contributor.request(
        "POST",
        f"/bounties/{bid}/applications",
        json={"cover_message": "Applying twice should not be allowed at all."},
    )
    assert dup.status_code == 409

    no_wallet = await requester.request("POST", f"/applications/{app['id']}/accept", json={"note": "Welcome"})
    assert no_wallet.status_code == 422 and no_wallet.json()["error"]["code"] == "contributor_wallet_missing"
    contrib_wallet = await link_wallet(contributor)
    accepted = await requester.post(f"/applications/{app['id']}/accept", {"note": "Welcome"})
    assert accepted["status"] == "ACCEPTED" and accepted["assignment_id"]
    assert (await requester.get(f"/bounties/{bid}"))["status"] == "IN_PROGRESS"

    # Optional on-chain assignment lock protects the contributor from refunds.
    await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {"action": "ASSIGN", "wallet_address": req_wallet, "assignment_id": accepted["assignment_id"]},
    )

    sub = await contributor.post(
        f"/bounties/{bid}/submissions",
        {
            "description": "Implemented the widget with tests and documentation included.",
            "evidence_url": "https://github.com/example/pr/1",
        },
        expected=201,
    )
    assert (await requester.get(f"/bounties/{bid}"))["status"] == "UNDER_REVIEW"
    await requester.post(f"/submissions/{sub['id']}/request-revision", {"feedback": "Please add dark mode."})
    assert (await requester.get(f"/bounties/{bid}"))["status"] == "IN_PROGRESS"
    resub = await contributor.patch(
        f"/submissions/{sub['id']}",
        {"description": "Implemented the widget with dark mode support and tests."},
    )
    assert resub["status"] == "RESUBMITTED" and resub["version"] == 2 and len(resub["revisions"]) == 2

    # Payout is impossible before approval.
    early = await requester.request(
        "POST",
        f"/bounties/{bid}/payouts/prepare",
        json={"wallet_address": req_wallet, "submission_id": sub["id"]},
    )
    assert early.status_code == 409
    approved = await requester.post(f"/submissions/{sub['id']}/approve", {"feedback": "Great"})
    assert approved["payment"]["payment_status"] == "CREATED"
    assert (await requester.get(f"/bounties/{bid}"))["status"] == "UNDER_REVIEW"  # until payout is verified

    payout = await chain_action(
        requester,
        f"/bounties/{bid}/payouts/prepare",
        {"wallet_address": req_wallet, "submission_id": sub["id"]},
    )
    assert payout["destination_address"] == contrib_wallet and payout["amount"] == "12.5000000"
    final = await requester.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED" and final["funding_status"] == "SETTLED"
    assert final["escrow"]["paid_out_amount"] == "12.5000000"
    paid = await contributor.get(f"/submissions/{sub['id']}")
    assert paid["payment"]["payment_status"] == "CONFIRMED"
    assert paid["payment"]["transaction"]["transaction_hash"] == payout["transaction_hash"]

    again = await requester.request(
        "POST",
        f"/bounties/{bid}/payouts/prepare",
        json={"wallet_address": req_wallet, "submission_id": sub["id"]},
    )
    assert again.status_code in (409, 422)  # no duplicate payouts

    stats = await contributor.get(f"/users/{contributor.me['username']}/stats")
    assert stats["contributions_completed"] == 1
    assert stats["total_rewards_received"] == "12.5000000"
    received = await contributor.get("/payments/me", params={"direction": "received"})
    assert received["total"] == 1

    activity = await client_factory().get(f"/bounties/{bid}/activity")
    actions = {a["action"] for a in activity["items"]}
    assert {"application.created", "submission.created", "payment.confirmed", "bounty.completed"} <= actions

    public = await client_factory().get("/analytics/public")
    assert public["network"] == "testnet"
    assert public["verified_payout_volume"] == "12.5000000"
    assert public["successful_transactions"] >= 3  # fund, assign, payout (each hash counted once)

    await drain_events()
    notes = await contributor.get("/notifications")
    kinds = {n["notification_type"] for n in notes["items"]}
    assert {"APPLICATION_ACCEPTED", "REVISION_REQUESTED", "SUBMISSION_APPROVED", "PAYMENT_CONFIRMED"} <= kinds
    await contributor.post("/notifications/read-all", expected=204)
    assert (await contributor.get("/notifications"))["unread_count"] == 0


async def test_accept_race_never_exceeds_positions(client_factory: Any, outbox_mail: Any) -> None:
    requester, wallet = await _requester(client_factory, outbox_mail, "race")
    bounty = await _funded(requester, wallet)
    applications = []
    for i in range(3):
        c = client_factory()
        await register(c, f"racer{i}_{id(c) % 10000}")
        await link_wallet(c)
        applications.append(
            await c.post(
                f"/bounties/{bounty['id']}/applications",
                {"cover_message": "I would love to work on this bounty right away."},
                expected=201,
            )
        )
    results = await asyncio.gather(
        *[requester.request("POST", f"/applications/{a['id']}/accept", json={}) for a in applications]
    )
    assert sorted(r.status_code for r in results).count(200) == 1
    detail = await requester.get(f"/bounties/{bounty['id']}")
    assert detail["positions_filled"] == 1


async def test_cancel_and_refund_restores_funds(client_factory: Any, outbox_mail: Any) -> None:
    requester, wallet = await _requester(client_factory, outbox_mail, "refund")
    unfunded = await _published(requester)
    cancelled = await requester.post(f"/bounties/{unfunded['id']}/cancel", {"reason": "No longer needed"})
    assert cancelled["status"] == "CANCELLED"

    bounty = await _funded(requester, wallet, reward_amount="7")
    bid = bounty["id"]
    requested = await requester.post(f"/bounties/{bid}/cancel", {"reason": "Scope changed"})
    assert requested["status"] == "CANCEL_REQUESTED" and requested["funding_status"] == "REFUND_PENDING"
    premature = await requester.request(
        "POST", f"/bounties/{bid}/chain/prepare", json={"action": "REFUND", "wallet_address": wallet}
    )
    assert premature.status_code == 409  # must request cancellation on-chain first
    await chain_action(
        requester, f"/bounties/{bid}/chain/prepare", {"action": "REQUEST_CANCEL", "wallet_address": wallet}
    )
    refund = await chain_action(
        requester, f"/bounties/{bid}/chain/prepare", {"action": "REFUND", "wallet_address": wallet}
    )
    assert refund["amount"] == "7.0000000"
    final = await requester.get(f"/bounties/{bid}")
    assert final["status"] == "CANCELLED" and final["funding_status"] == "REFUNDED"
    assert final["escrow"]["refunded_amount"] == "7.0000000"


async def test_dispute_freezes_payouts_and_moderator_resolves(
    client_factory: Any, outbox_mail: Any, db_session: Any
) -> None:
    from sqlalchemy import update

    from app.modules.users.models import Role, User

    requester, wallet = await _requester(client_factory, outbox_mail, "dispute")
    bounty = await _funded(requester, wallet)
    bid = bounty["id"]
    contributor = client_factory()
    await register(contributor, "dispute_contrib")
    await link_wallet(contributor)
    app = await contributor.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "Ready to deliver this with high quality and tests."},
        expected=201,
    )
    await requester.post(f"/applications/{app['id']}/accept", {})
    sub = await contributor.post(
        f"/bounties/{bid}/submissions",
        {"description": "Delivered the full scope as described in the bounty."},
        expected=201,
    )
    dispute = await contributor.post(
        f"/bounties/{bid}/disputes",
        {"reason": "The requester has not reviewed my submission for a long time."},
        expected=201,
    )
    assert dispute["status"] == "OPEN" and dispute["escrow_frozen_onchain"] is False
    assert (await requester.get(f"/bounties/{bid}"))["status"] == "DISPUTED"
    frozen = await requester.request("POST", f"/submissions/{sub['id']}/approve", json={})
    assert frozen.status_code == 409

    outsider = client_factory()
    await register(outsider)
    await outsider.request("GET", f"/disputes/{dispute['id']}", expected=404)
    await outsider.request(
        "POST",
        f"/disputes/{dispute['id']}/resolve",
        json={"resolution": "DISMISSED", "note": "not allowed to do this"},
        expected=403,
    )

    moderator = client_factory()
    mod = await register(moderator, "the_moderator")
    await db_session.execute(update(User).where(User.username == mod["username"]).values(role=Role.MODERATOR))
    await db_session.commit()
    await moderator.post(f"/disputes/{dispute['id']}/evidence", {"description": "Reviewed the timeline."})
    resolved = await moderator.post(
        f"/disputes/{dispute['id']}/resolve",
        {"resolution": "RELEASE_TO_CONTRIBUTOR", "note": "Work meets the acceptance criteria."},
    )
    assert resolved["status"] == "RESOLVED" and resolved["requires_onchain_execution"] is False
    after = await requester.get(f"/bounties/{bid}")
    assert after["status"] == "UNDER_REVIEW"  # approved, awaiting the requester's signed payout
    approved = await requester.get(f"/submissions/{sub['id']}")
    assert approved["status"] == "APPROVED" and approved["payment"]["payment_status"] == "CREATED"


async def test_rbac_admin_endpoints(client_factory: Any, db_session: Any) -> None:
    from sqlalchemy import update

    from app.modules.users.models import Role, User

    user = client_factory()
    await register(user, "plain_user")
    await user.request("GET", "/admin/users", expected=403)
    await user.request("GET", "/admin/audit-logs", expected=403)
    await user.request("GET", "/analytics/platform", expected=403)

    mod_client = client_factory()
    mod = await register(mod_client, "mod_user")
    admin_client = client_factory()
    admin = await register(admin_client, "admin_user")
    await db_session.execute(update(User).where(User.username == mod["username"]).values(role=Role.MODERATOR))
    await db_session.execute(update(User).where(User.username == admin["username"]).values(role=Role.ADMIN))
    await db_session.commit()

    assert (await mod_client.get("/admin/users"))["total"] >= 3
    await mod_client.get("/admin/bounties")
    target = (await mod_client.get("/admin/users", params={"q": "plain_user"}))["items"][0]
    await mod_client.request(
        "PATCH", f"/admin/users/{target['id']}", json={"role": "MODERATOR"}, expected=403
    )
    me_mod = await mod_client.get("/auth/me")
    assert "user:assign_role" not in me_mod["permissions"] and "dispute:resolve" in me_mod["permissions"]

    promoted = await admin_client.patch(f"/admin/users/{target['id']}", {"role": "MODERATOR"})
    assert promoted["role"] == "MODERATOR"
    own = (await admin_client.get("/auth/me"))["id"]
    await admin_client.request(
        "PATCH", f"/admin/users/{own}", json={"role": "USER"}, expected=(403, 409, 422)
    )
    suspended = await admin_client.patch(f"/admin/users/{target['id']}", {"is_active": False})
    assert suspended["is_active"] is False
    await user.request("GET", "/auth/me", expected=(401, 403))  # suspended users lose access immediately
