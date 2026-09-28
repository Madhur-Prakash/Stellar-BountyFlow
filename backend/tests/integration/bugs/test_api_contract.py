"""Every response shape documented in docs/api.md is served with (at least) the documented fields and enum
values. The backend may add fields (documented as extensions); it must never drop or rename one."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.api.conftest import drain_events
from tests.integration.bugs.helpers import (
    assign,
    contributor,
    funded,
    moderator,
    payout,
    published,
    requester,
    submit_work,
)

MONEY = re.compile(r"^\d+\.\d{7}$")

PAGE = {"items", "total", "page", "page_size", "pages"}
USER_SUMMARY = {"id", "username", "display_name", "avatar_url"}
ASSET = {"code", "issuer", "type", "contract_id"}
ME = {
    "id",
    "email",
    "email_verified",
    "username",
    "display_name",
    "avatar_url",
    "bio",
    "role",
    "skills",
    "interests",
    "github_url",
    "portfolio_url",
    "wants_to_request",
    "wants_to_contribute",
    "onboarding",
    "created_at",
}
ONBOARDING = {
    "email_verified",
    "profile_completed",
    "role_selected",
    "wallet_connected",
    "first_action_taken",
    "completed",
}
WALLET = {"id", "public_address", "network", "verification_status", "verified_at", "created_at"}
USER_STATS = {
    "bounties_created",
    "bounties_completed_as_requester",
    "contributions_completed",
    "applications_submitted",
    "acceptance_rate",
    "approval_rate",
    "total_rewards_received",
    "total_rewards_paid",
}
PUBLIC_PROFILE = {
    "id",
    "username",
    "display_name",
    "avatar_url",
    "bio",
    "skills",
    "interests",
    "github_url",
    "portfolio_url",
    "joined_at",
    "wallets",
    "stats",
}
ESCROW = {
    "contract_id",
    "network",
    "asset",
    "onchain_bounty_id",
    "required_amount",
    "funded_amount",
    "paid_out_amount",
    "refunded_amount",
    "state",
    "last_reconciled_at",
}
SUMMARY = {
    "id",
    "slug",
    "title",
    "short_description",
    "category",
    "difficulty",
    "tags",
    "required_skills",
    "reward_amount",
    "reward_asset",
    "total_reward",
    "network",
    "status",
    "funding_status",
    "application_deadline",
    "completion_deadline",
    "positions_available",
    "positions_filled",
    "applications_count",
    "requester",
    "is_featured",
    "is_bookmarked",
    "created_at",
    "published_at",
}
DETAIL = SUMMARY | {
    "description",
    "eligibility_criteria",
    "submission_requirements",
    "acceptance_criteria",
    "repository_url",
    "links",
    "visibility",
    "escrow",
    "viewer",
}
VIEWER = {"is_owner", "is_assigned", "can_apply", "can_submit", "application", "assignment_id"}
APPLICATION = {
    "id",
    "bounty_id",
    "bounty",
    "contributor",
    "cover_message",
    "relevant_experience",
    "work_samples",
    "status",
    "review_note",
    "reviewed_at",
    "created_at",
    "updated_at",
}
SUBMISSION = {
    "id",
    "bounty_id",
    "bounty",
    "contributor",
    "assignment_id",
    "version",
    "description",
    "evidence_url",
    "evidence_links",
    "status",
    "review_feedback",
    "reviewer",
    "reviewed_at",
    "payment",
    "created_at",
    "updated_at",
}
PAYMENT = {
    "id",
    "bounty_id",
    "contributor",
    "submission_id",
    "amount",
    "asset",
    "payment_status",
    "transaction",
    "created_at",
    "settled_at",
}
TX = {
    "id",
    "bounty_id",
    "bounty_title",
    "user",
    "transaction_hash",
    "transaction_type",
    "network",
    "amount",
    "asset",
    "status",
    "source_address",
    "destination_address",
    "ledger_sequence",
    "submitted_at",
    "confirmed_at",
    "failure_reason",
    "explorer_url",
    "created_at",
}
PREPARED = {
    "transaction",
    "unsigned_xdr",
    "network_passphrase",
    "network",
    "summary",
    "expires_at",
}
TX_SUMMARY = {
    "action",
    "description",
    "amount",
    "asset",
    "fee_estimate_stroops",
    "contract_id",
    "function_name",
}
ACTIVITY = {"id", "action", "actor", "entity_type", "entity_id", "bounty", "metadata", "created_at", "link"}
NOTIFICATION = {"id", "notification_type", "title", "message", "payload", "link", "read_at", "created_at"}
DISPUTE = {
    "id",
    "bounty",
    "raised_by",
    "reason",
    "status",
    "assigned_moderator",
    "resolution",
    "resolution_note",
    "evidence",
    "created_at",
    "resolved_at",
}
EVIDENCE = {"id", "submitted_by", "description", "url", "created_at"}
DASHBOARD = {
    "active_bounties",
    "pending_applications_to_review",
    "submissions_awaiting_review",
    "pending_payments",
    "my_pending_applications",
    "my_active_assignments",
    "revision_requests",
    "recent_completed",
    "recent_activity",
    "recommendations",
}
PUBLIC_STATS = {
    "network",
    "generated_at",
    "registered_users",
    "published_bounties",
    "open_bounties",
    "funded_bounties",
    "completed_bounties",
    "verified_payout_volume",
    "successful_transactions",
    "unique_transacting_wallets",
    "methodology",
}
REQUESTER_ANALYTICS = {
    "bounties_by_status",
    "total_escrowed",
    "total_paid",
    "applications_received",
    "avg_time_to_first_application_hours",
    "spending_by_month",
}
CONTRIBUTOR_ANALYTICS = {
    "applications_by_status",
    "submissions_by_status",
    "total_earned",
    "earnings_by_month",
    "completed_count",
}
CONTRIBUTION = {"bounty", "completed_at", "amount", "transaction_hash"}
BOUNTY_STATUSES = {
    "DRAFT",
    "OPEN",
    "FUNDING_PENDING",
    "FUNDED",
    "IN_PROGRESS",
    "UNDER_REVIEW",
    "COMPLETED",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "DISPUTED",
    "EXPIRED",
}
FUNDING_STATUSES = {
    "UNFUNDED",
    "PENDING",
    "PARTIALLY_FUNDED",
    "FUNDED",
    "REFUND_PENDING",
    "REFUNDED",
    "SETTLED",
}


def has(obj: dict[str, Any], keys: set[str], what: str) -> None:
    missing = keys - obj.keys()
    assert not missing, f"{what} is missing documented fields {sorted(missing)}"


def money(value: Any) -> None:
    assert isinstance(value, str) and MONEY.match(value), value


def check_summary(b: dict[str, Any]) -> None:
    has(b, SUMMARY, "BountySummary")
    has(b["requester"], USER_SUMMARY, "UserSummary")
    has(b["reward_asset"], ASSET, "Asset")
    assert b["status"] in BOUNTY_STATUSES and b["funding_status"] in FUNDING_STATUSES
    money(b["reward_amount"])
    money(b["total_reward"])


def check_tx(t: dict[str, Any]) -> None:
    has(t, TX, "BlockchainTransaction")
    if t["amount"] is not None:
        money(t["amount"])


async def test_documented_shapes(client_factory: Any, outbox_mail: Any, db_session: AsyncSession) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    me = await req.get("/auth/me")
    has(me, ME, "Me")
    has(me["onboarding"], ONBOARDING, "Me.onboarding")
    for w in await req.get("/wallets"):
        has(w, WALLET, "Wallet")

    draft = await req.post("/bounties", {**_payload()}, expected=201)
    has(draft, DETAIL, "BountyDetail")
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    check_summary(bounty)
    has(bounty, DETAIL, "BountyDetail")
    has(bounty["viewer"], VIEWER, "BountyDetail.viewer")
    has(bounty["escrow"], ESCROW, "EscrowView")
    for key in ("required_amount", "funded_amount", "paid_out_amount", "refunded_amount"):
        money(bounty["escrow"][key])

    anon = client_factory()
    anon_detail = await anon.get(f"/bounties/{bid}")
    assert anon_detail["viewer"] is None
    market = await anon.get("/bounties")
    has(market, PAGE, "Page")
    for item in market["items"]:
        check_summary(item)
    for item in await anon.get("/bounties/featured"):
        check_summary(item)

    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)
    apps = await req.get(f"/bounties/{bid}/applications")
    has(apps, PAGE, "Page")
    has(apps["items"][0], APPLICATION, "Application")
    has(apps["items"][0]["contributor"], USER_SUMMARY | {"skills"}, "Application.contributor")
    has(apps["items"][0]["bounty"], {"id", "slug", "title", "status"}, "Application.bounty")

    sub = await submit_work(dev, bid)
    has(sub, SUBMISSION, "Submission")
    approved = await req.post(f"/submissions/{sub['id']}/approve", {})
    has(approved["payment"], PAYMENT, "PaymentRecord")
    money(approved["payment"]["amount"])

    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    has(prepared, PREPARED, "PreparedTransaction")
    has(prepared["summary"], TX_SUMMARY, "PreparedTransaction.summary")
    check_tx(prepared["transaction"])
    tx = await payout(req, bid, wallet, sub["id"])
    check_tx(tx)
    for t in await req.get(f"/bounties/{bid}/transactions"):
        check_tx(t)
    mine = await req.get("/transactions/me")
    has(mine, PAGE, "Page")
    funding = await req.get(f"/bounties/{bid}/funding")
    has(funding, {"funding_status", "escrow", "transactions"}, "Funding")
    payments = await dev.get("/payments/me", params={"direction": "received"})
    has(payments["items"][0], PAYMENT, "PaymentRecord")
    check_tx(payments["items"][0]["transaction"])

    activity = await anon.get(f"/bounties/{bid}/activity")
    has(activity, PAGE, "Page")
    has(activity["items"][0], ACTIVITY, "ActivityItem")

    await drain_events()
    notes = await dev.get("/notifications")
    has(notes, PAGE | {"unread_count"}, "Page<Notification>")
    has(notes["items"][0], NOTIFICATION, "Notification")
    prefs = await dev.get("/notification-preferences")
    has(prefs, {"email_enabled", "types"}, "NotificationPreferences")
    assert set(prefs["types"]["PAYMENT_CONFIRMED"]) >= {"in_app", "email"}

    stats = await dev.get(f"/users/{dev.me['username']}/stats")
    has(stats, USER_STATS, "UserStats")
    profile = await anon.get(f"/users/{dev.me['username']}")
    has(profile, PUBLIC_PROFILE, "PublicProfile")
    has(profile["wallets"][0], {"public_address", "network", "verified_at"}, "PublicProfile.wallets")
    contributions = await anon.get(f"/users/{dev.me['username']}/contributions")
    has(contributions["items"][0], CONTRIBUTION, "Contribution")
    check_summary(contributions["items"][0]["bounty"])

    dashboard = await req.get("/dashboard")
    has(dashboard, DASHBOARD, "Dashboard")
    public_stats = await anon.get("/analytics/public")
    has(public_stats, PUBLIC_STATS, "PublicStats")
    money(public_stats["verified_payout_volume"])
    mine_analytics = await req.get("/analytics/me")
    has(mine_analytics["requester"], REQUESTER_ANALYTICS, "RequesterAnalytics")
    has(mine_analytics["contributor"], CONTRIBUTOR_ANALYTICS, "ContributorAnalytics")
    assert set(mine_analytics["requester"]["bounties_by_status"]) == BOUNTY_STATUSES

    other = await published(req)
    dev2, _ = await contributor(client_factory)
    await dev2.post(
        f"/bounties/{other['id']}/applications",
        {"cover_message": "I'd like to take this one as well, thanks!"},
        expected=201,
    )
    funded_other = await funded(req, wallet)
    await assign(req, dev2, funded_other["id"])
    dispute = await dev2.post(
        f"/bounties/{funded_other['id']}/disputes",
        {
            "reason": "Checking the dispute response shape end to end.",
            "evidence_url": "https://example.com/e",
        },
        expected=201,
    )
    has(dispute, DISPUTE, "Dispute")
    has(dispute["evidence"][0], EVIDENCE, "Dispute.evidence")
    assert isinstance(await dev2.get("/disputes/me"), list)
    mod = await moderator(client_factory, db_session)
    queue = await mod.get("/admin/disputes")
    has(queue, PAGE, "Page")


async def test_error_envelope_and_status_codes(client_factory: Any) -> None:
    anon = client_factory()
    missing = await anon.request("GET", "/bounties/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    body = missing.json()["error"]
    assert body["code"] == "not_found" and body["message"] and "request_id" in body
    unauth = await anon.request("GET", "/auth/me")
    assert unauth.status_code == 401 and unauth.json()["error"]["code"] in (
        "not_authenticated",
        "token_expired",
    )
    invalid = await anon.request("GET", "/bounties", params={"page_size": 1000})
    assert invalid.status_code == 422
    details = invalid.json()["error"]["details"]
    assert isinstance(details, list) and {"field", "message"} <= set(details[0])


def _payload() -> dict[str, Any]:
    from tests.integration.api.conftest import bounty_payload

    return bounty_payload()
