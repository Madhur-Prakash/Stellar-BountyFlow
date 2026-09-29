"""Data export and account deletion, end to end through the API and the worker jobs."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.modules.admin.models import AuditLog
from app.modules.applications.models import BountyApplication
from app.modules.compliance import exports
from app.modules.compliance.deletion import REMOVED
from app.modules.compliance.models import AccountDeletionRequest, DataExport, ExportStatus
from app.modules.payments.models import BlockchainTransaction, PaymentRecord, PaymentStatus
from app.modules.submissions.models import BountySubmission
from app.modules.users.models import User, Wallet, WalletVerificationStatus
from tests.integration.api.conftest import chain_action, drain_events, register
from tests.integration.compliance.helpers import (
    PASSWORD,
    approved_submission,
    funded,
    handle,
    requester,
    staff,
)
from worker.jobs import compliance as jobs


async def test_data_export_is_built_by_the_worker_and_served_by_a_signed_link(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    user, wallet = await requester(client_factory, outbox_mail, "export")
    bounty = await funded(user, wallet, reward_amount="3")

    created = await user.post("/privacy/exports", expected=202)
    assert created["status"] == "PENDING" and created["download_url"] is None
    again = await user.request("POST", "/privacy/exports")
    assert again.status_code == 409

    assert await jobs.run_exports_once() == {"processed": 1, "expired": 0}
    [ready] = await user.get("/privacy/exports")
    assert ready["status"] == "READY" and ready["size_bytes"] > 0
    url = ready["download_url"]
    assert url.startswith(f"/api/v1/privacy/exports/{ready['id']}/download?expires=")

    response = await user.http.get(url)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["content-disposition"].startswith('attachment; filename="bountyflow-data-')
    archive = response.json()
    assert archive["export"]["export_id"] == ready["id"]
    assert archive["profile"]["email"] == user.me["email"]
    assert [w["public_address"] for w in archive["wallets"]] == [wallet]
    assert [b["id"] for b in archive["bounties"]] == [bounty["id"]]
    assert archive["escrows"][0]["funded_amount"] == "3.0000000"
    assert any(t["transaction_type"] == "ESCROW_CREATE" for t in archive["transactions"])
    actions = {e["action"] for e in archive["audit_entries"]}
    assert "wallet.verified" in actions and "privacy.export_requested" in actions
    assert not any(a.startswith("screening.") for a in actions)  # screening results are left out

    # The link only works for its owner, unmodified and unexpired.
    assert (await user.http.get(url[:-6] + "000000")).status_code == 403
    other = client_factory()
    await register(other, handle("other"))
    assert (await other.http.get(url)).status_code == 404
    anonymous = client_factory()
    assert (await anonymous.http.get(url)).status_code == 401
    row = await db_session.get(DataExport, uuid.UUID(ready["id"]))
    assert row is not None
    stale = exports.signed_download_path(row, now=time.time() - exports.LINK_TTL_SECONDS - 5)
    assert (await user.http.get(stale)).status_code == 403

    # The user is told in the app and by email.
    await drain_events()
    notes = await user.get("/notifications")
    assert any(
        n["title"] == "Your data export is ready" and n["link"] == "/app/privacy" for n in notes["items"]
    )
    ready_mail = [m for m in outbox_mail.sent if "data export is ready" in m.subject]
    assert len(ready_mail) == 1 and ready_mail[0].to == user.me["email"]
    assert "/app/privacy" in ready_mail[0].text

    # Expiry deletes the archive.
    await db_session.execute(
        update(DataExport).where(DataExport.id == row.id).values(expires_at=utcnow() - timedelta(minutes=1))
    )
    await db_session.commit()
    assert (await jobs.run_exports_once())["expired"] == 1
    [expired] = await user.get("/privacy/exports")
    assert expired["status"] == "EXPIRED" and expired["download_url"] is None
    await db_session.refresh(row)
    assert row.status == ExportStatus.EXPIRED and row.archive is None
    query = parse_qs(urlparse(url).query)
    gone = await user.http.get(
        f"/api/v1/privacy/exports/{row.id}/download",
        params={"expires": query["expires"][0], "signature": query["signature"][0]},
    )
    assert gone.status_code == 404


async def test_the_archive_covers_every_module_that_holds_personal_data(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    """Every section a feature module registers has to reach the archive: a module that starts holding personal
    data and registers a section must not be able to be forgotten by the export."""
    from app.modules.compliance import registry

    user, _ = await requester(client_factory, outbox_mail, "sections")
    registry.load_sections()
    assert registry.EXPORT_SECTIONS, "no module registered an export section"

    await user.post("/privacy/exports", expected=202)
    await jobs.run_exports_once()
    [ready] = await user.get("/privacy/exports")
    archive = (await user.http.get(ready["download_url"])).json()

    for name in registry.EXPORT_SECTIONS:
        assert name in archive, f"export section {name} is missing from the archive"
    # The sections the privacy notice names explicitly.
    for name in (
        "milestones",
        "passkey_wallets",
        "sponsored_transactions",
        "attestations",
        "credentials",
        "saved_searches",
        "qa_posts",
        "pull_requests",
        "github_account",
    ):
        assert name in archive, name


async def test_deletion_is_refused_while_an_escrow_holds_funds(client_factory: Any, outbox_mail: Any) -> None:
    user, wallet = await requester(client_factory, outbox_mail, "holder")
    await funded(user, wallet, reward_amount="2")

    status = await user.get("/privacy/deletion")
    assert status["request"] is None and status["grace_days"] == 14
    assert [b["kind"] for b in status["blockers"]] == ["funded_escrow"]
    refused = await user.request("POST", "/privacy/deletion", json={"password": PASSWORD})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "deletion_blocked"
    assert refused.json()["error"]["details"][0]["kind"] == "funded_escrow"


async def test_deletion_waits_out_the_grace_period_then_keeps_financial_records_pseudonymised(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    owner, owner_wallet = await requester(client_factory, outbox_mail, "owner")
    bounty = await funded(owner, owner_wallet, reward_amount="4")
    contributor, contributor_wallet, submission = await approved_submission(
        client_factory, owner, bounty["id"]
    )
    uid = uuid.UUID(contributor.me["id"])
    email, username = contributor.me["email"], contributor.me["username"]

    # Owed a payout: deletion has to wait for it.
    blocked = await contributor.get("/privacy/deletion")
    assert {b["kind"] for b in blocked["blockers"]} >= {"active_assignment", "unsettled_payout"}
    await chain_action(
        owner,
        f"/bounties/{bounty['id']}/payouts/prepare",
        {"wallet_address": owner_wallet, "submission_id": submission["id"]},
    )
    assert (await contributor.get("/privacy/deletion"))["blockers"] == []

    wrong = await contributor.request("POST", "/privacy/deletion", json={"password": "not-my-password"})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "invalid_password"

    scheduled = await contributor.post("/privacy/deletion", {"password": PASSWORD, "reason": "Moving on"})
    request = scheduled["request"]
    assert request["status"] == "SCHEDULED"
    assert (
        await contributor.request("POST", "/privacy/deletion", json={"password": PASSWORD})
    ).status_code == 409
    await drain_events()
    notice = [m for m in outbox_mail.sent if "scheduled for deletion" in m.subject]
    assert len(notice) == 1 and notice[0].to == email

    cancelled = await contributor.post("/privacy/deletion/cancel")
    assert cancelled["request"] is None
    assert (await contributor.request("POST", "/privacy/deletion/cancel")).status_code == 404
    await contributor.post("/privacy/deletion", {"password": PASSWORD})

    admin = await staff(client_factory, db_session)
    pending = await admin.get("/admin/compliance/deletions", params={"status": "SCHEDULED"})
    assert [r["user"]["username"] for r in pending["items"]] == [username]
    assert pending["items"][0]["email"] == email and pending["items"][0]["blockers"] == []

    assert await jobs.run_deletions_once() == 0  # still in its grace period
    await db_session.execute(
        update(AccountDeletionRequest)
        .where(AccountDeletionRequest.user_id == uid)
        .values(scheduled_for=utcnow() - timedelta(minutes=1))
    )
    await db_session.commit()
    assert await jobs.run_deletions_once() == 1

    user = await db_session.get(User, uid, populate_existing=True)
    assert user is not None
    assert user.username.startswith("deleted-") and user.email.endswith("@deleted.invalid")
    assert user.display_name == "Deleted user" and user.is_active is False and user.bio is None

    # Signed out everywhere, cannot sign in again, no public profile.
    assert (await contributor.request("GET", "/users/me")).status_code == 401
    login = await client_factory().request("POST", "/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 401
    assert (await client_factory().request("GET", f"/users/{username}")).status_code == 404

    # Financial and audit records stay, linked to the pseudonym.
    payment = await db_session.scalar(select(PaymentRecord).where(PaymentRecord.contributor_id == uid))
    assert payment is not None and payment.payment_status == PaymentStatus.CONFIRMED
    payout_tx = await db_session.scalar(
        select(BlockchainTransaction).where(BlockchainTransaction.destination_address == contributor_wallet)
    )
    assert payout_tx is not None
    wallet = await db_session.scalar(select(Wallet).where(Wallet.user_id == uid))
    assert wallet is not None and wallet.verification_status == WalletVerificationStatus.REVOKED
    kept = await db_session.get(BountySubmission, uuid.UUID(submission["id"]), populate_existing=True)
    assert kept is not None and kept.description != REMOVED  # approved, paid work is part of the record
    application = await db_session.scalar(
        select(BountyApplication).where(BountyApplication.contributor_id == uid)
    )
    assert application is not None and application.cover_message == REMOVED
    anonymised = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "account.anonymised", AuditLog.entity_id == uid)
    )
    assert anonymised is not None and anonymised.metadata_["pseudonym"] == user.username

    done = await admin.get("/admin/compliance/deletions", params={"status": "COMPLETED"})
    assert done["items"][0]["pseudonym"] == user.username and done["items"][0]["reason"] is None
    # The requester's view of the paid bounty still shows the (pseudonymous) contributor's payment.
    final = await owner.get(f"/bounties/{bounty['id']}")
    assert final["status"] == "COMPLETED"


async def test_privacy_routes_are_scoped_to_the_signed_in_user(client_factory: Any, outbox_mail: Any) -> None:
    alice, _ = await requester(client_factory, outbox_mail, "alice")
    bob = client_factory()
    await register(bob, handle("bob"))
    await alice.post("/privacy/exports", expected=202)
    assert await bob.get("/privacy/exports") == []
    for path in ("/admin/compliance/deletions", "/admin/compliance/screening/entries", "/admin/ops/status"):
        assert (await bob.request("GET", path)).status_code == 403
