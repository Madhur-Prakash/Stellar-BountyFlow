"""On-chain completion attestations and verifiable credentials, end to end through the API.

An attestation states one *completion*: a contributor whose position on a bounty is fully paid, whatever mix of
releases, milestone payouts, batch legs or claims paid it. These tests drive the real lifecycle through the API.

The escrow runs on `FakeStellarChain` and the attestation registry on `FakeAttestationChain`; both model their
contracts, so these tests cover the pipeline's idempotency, verification and reconciliation logic. The real
network path is covered by frontend/e2e/reputation.spec.ts on Stellar Testnet.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update
from stellar_sdk import Keypair

from app.core.config import get_settings
from app.core.security import utcnow
from app.db.session import get_sessionmaker
from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.credentials import status_list
from app.modules.reputation import chain as reputation_chain
from app.modules.reputation import service as reputation_service
from app.modules.reputation.models import AttestationStatus, ChainCheck, CompletionAttestation
from app.modules.users.models import Role
from tests.integration.api.conftest import (
    ApiClient,
    bounty_payload,
    chain_action,
    drain_events,
    link_wallet,
    register,
    verify_email,
)
from tests.integration.security.helpers import set_role
from tests.support.fake_attestations import FakeAttestationChain
from tests.support.fake_chain import FakeStellarChain

REGISTRY = "CBXJVFUQHWECJZQSEBAFGHXLHP72PCPUX7XES42KVEMVAMZ26D5CZ33N"
ATTESTER = Keypair.random()
ISSUER = Keypair.random()


def _enable(monkeypatch: pytest.MonkeyPatch, *, attestations: bool = True, credentials: bool = True) -> None:
    for key, value in (
        ("ATTESTATION_CONTRACT_ID", REGISTRY if attestations else ""),
        ("STELLAR_ATTESTER_SECRET", ATTESTER.secret if attestations else ""),
        ("CREDENTIAL_ISSUER_SECRET", ISSUER.secret if credentials else ""),
    ):
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture
async def registry(
    chain: FakeStellarChain, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeAttestationChain]:
    _enable(monkeypatch)
    fake = FakeAttestationChain(reputation_chain.get_config())
    reputation_chain.set_chain(fake)
    try:
        yield fake
    finally:
        reputation_chain.set_chain(None)


async def _pipeline() -> int:
    async with get_sessionmaker()() as session:
        return await reputation_service.run_pipeline(session, limit=50)


async def _row(**where: Any) -> CompletionAttestation:
    async with get_sessionmaker()() as session:
        stmt = select(CompletionAttestation)
        for key, value in where.items():
            stmt = stmt.where(getattr(CompletionAttestation, key) == value)
        row = await session.scalar(stmt)
        assert row is not None
        return row


async def _paid_contribution(
    client_factory: Any, mail: Any, *, reward: str = "12.5"
) -> tuple[ApiClient, ApiClient, str, dict[str, Any], str]:
    """A bounty paid out on-chain: (requester, contributor, bounty id, payout tx, contributor wallet)."""
    requester = client_factory()
    await register(requester, f"rep_req_{uuid.uuid4().hex[:6]}")
    await verify_email(requester, mail)
    req_wallet = await link_wallet(requester)
    bounty = await requester.post("/bounties", bounty_payload(reward_amount=reward), expected=201)
    bid = bounty["id"]
    await requester.post(f"/bounties/{bid}/publish")
    await chain_action(requester, f"/bounties/{bid}/funding/prepare", {"wallet_address": req_wallet})

    contributor = client_factory()
    await register(contributor, f"rep_dev_{uuid.uuid4().hex[:6]}")
    wallet = await link_wallet(contributor)
    application = await contributor.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "I have shipped this exact kind of work many times before."},
        expected=201,
    )
    await requester.post(f"/applications/{application['id']}/accept", {"note": "Welcome"})
    sub = await contributor.post(
        f"/bounties/{bid}/submissions",
        {"description": "Delivered everything described in the acceptance criteria."},
        expected=201,
    )
    await requester.post(f"/submissions/{sub['id']}/approve", {"feedback": "Great"})
    payout = await chain_action(
        requester,
        f"/bounties/{bid}/payouts/prepare",
        {"wallet_address": req_wallet, "submission_id": sub["id"]},
    )
    return requester, contributor, bid, payout, wallet


# --- Attestations -------------------------------------------------------------------------


async def test_verified_payout_is_attested_on_chain_and_shown(
    client_factory: Any, outbox_mail: Any, registry: FakeAttestationChain
) -> None:
    _requester, contributor, bid, payout, wallet = await _paid_contribution(client_factory, outbox_mail)
    username = contributor.me["username"]  # type: ignore[index]
    anon = client_factory()

    await drain_events()  # payment.confirmed -> queued (nothing on-chain yet, so nothing public)
    queued = await _row(bounty_id=uuid.UUID(bid))
    assert queued.status == AttestationStatus.PENDING
    assert (await anon.get(f"/users/{username}/attestations"))["total"] == 0
    assert (await anon.get(f"/users/{username}/reputation"))["attested_completions"] == 0
    mine = await contributor.get("/reputation/me/attestations")
    assert mine["total"] == 1 and mine["items"][0]["status"] == "PENDING"

    assert await _pipeline() == 1
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.CONFIRMED and row.onchain_id == 1
    assert row.chain_check == ChainCheck.MATCH and row.attestation_tx_hash
    record = registry.records[1]
    assert record.contributor == wallet and record.payout_tx == payout["transaction_hash"]
    assert record.amount == 125_000_000 and record.escrow_contract == get_settings().soroban_contract_id

    public = await anon.get(f"/users/{username}/attestations")
    assert public["total"] == 1
    item = public["items"][0]
    assert item["onchain_id"] == 1 and item["amount"] == "12.5000000" and item["asset"]["code"] == "XLM"
    assert item["payments_count"] == 1  # one release paid this completion in full
    assert item["bounty"]["id"] == bid and item["contributor_address"] == wallet
    assert (
        item["payout_explorer_url"]
        == f"https://stellar.expert/explorer/testnet/tx/{payout['transaction_hash']}"
    )
    assert item["attestation_explorer_url"].endswith(row.attestation_tx_hash)
    assert item["contract_explorer_url"].endswith(f"/contract/{REGISTRY}")

    summary = await anon.get(f"/users/{username}/reputation")
    assert summary["enabled"] is True and summary["attested_completions"] == 1
    assert (
        summary["earned"] == [{"asset": summary["earned"][0]["asset"], "amount": "12.5000000"}]
        and summary["earned"][0]["asset"]["code"] == "XLM"
    )
    assert summary["attester_address"] == ATTESTER.public_key

    detail = await anon.get("/attestations/1")
    assert detail["id"] == str(row.id) and detail["chain"]["found"] is True
    assert detail["chain"]["matches"] is True and detail["chain"]["revoked"] is False
    assert (await anon.get(f"/attestations/{row.id}"))["onchain_id"] == 1
    await anon.request("GET", "/attestations/99", expected=404)

    # Replaying the event and running the pipeline again changes nothing (one row, one on-chain record).
    await drain_events()
    await _pipeline()
    assert len(registry.records) == 1 and len(registry.submitted) == 1
    async with get_sessionmaker()() as session:
        rows = (await session.scalars(select(CompletionAttestation))).unique().all()
    assert len(rows) == 1  # one attestation per (bounty, contributor), however many transfers paid it


async def test_a_partially_paid_position_is_not_attested(
    client_factory: Any, outbox_mail: Any, registry: FakeAttestationChain
) -> None:
    """A milestone payout that does not complete the position (the contract has not marked the contributor
    ``Paid``, so the assignment is still ACTIVE) queues nothing."""
    _r, _c, bid, payout, _w = await _paid_contribution(client_factory, outbox_mail)
    async with get_sessionmaker()() as session:
        await session.execute(
            update(BountyAssignment)
            .where(BountyAssignment.bounty_id == uuid.UUID(bid))
            .values(status=AssignmentStatus.ACTIVE, completed_at=None)
        )
        await session.execute(update(CompletionAttestation).values(status=AttestationStatus.FAILED))
        await session.commit()
    await drain_events()
    async with get_sessionmaker()() as session:
        queued = await session.scalar(
            select(CompletionAttestation).where(CompletionAttestation.status == AttestationStatus.PENDING)
        )
    assert queued is None and payout["status"] == "CONFIRMED"


async def test_lost_response_is_adopted_not_attested_twice(
    client_factory: Any, outbox_mail: Any, registry: FakeAttestationChain
) -> None:
    _r, _c, bid, _payout, _w = await _paid_contribution(client_factory, outbox_mail)
    await drain_events()
    registry.lose_next_response = True  # applied on-chain, but the response never arrives
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.PENDING and row.attempts == 1 and len(registry.records) == 1

    await _release_backoff()
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.CONFIRMED and row.onchain_id == 1
    assert len(registry.records) == 1 and len(registry.submitted) == 1  # adopted via find(), never resent


async def _release_backoff() -> None:
    async with get_sessionmaker()() as session:
        await session.execute(update(CompletionAttestation).values(next_attempt_at=utcnow()))
        await session.commit()


async def test_failed_and_dropped_transactions_are_retried(
    client_factory: Any, outbox_mail: Any, registry: FakeAttestationChain
) -> None:
    _r, _c, bid, _payout, _w = await _paid_contribution(client_factory, outbox_mail)
    await drain_events()

    registry.fail_next = True
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.PENDING and row.last_error and not registry.records

    registry.drop_next = True  # sent, never included
    await _release_backoff()
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.SUBMITTED
    await _release_backoff()
    await _pipeline()  # still inside its time bounds: keep waiting
    assert (await _row(bounty_id=uuid.UUID(bid))).status == AttestationStatus.SUBMITTED

    async with get_sessionmaker()() as session:  # the time bounds and grace period have passed
        await session.execute(
            update(CompletionAttestation).values(
                submitted_at=utcnow() - timedelta(hours=1), next_attempt_at=utcnow()
            )
        )
        await session.commit()
    await _pipeline()
    assert (await _row(bounty_id=uuid.UUID(bid))).status == AttestationStatus.PENDING
    await _release_backoff()
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.CONFIRMED and len(registry.records) == 1


async def test_rpc_outage_defers_without_losing_the_row(
    client_factory: Any, outbox_mail: Any, registry: FakeAttestationChain
) -> None:
    _r, _c, bid, _payout, _w = await _paid_contribution(client_factory, outbox_mail)
    await drain_events()
    registry.rpc_down = True
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.PENDING and row.next_attempt_at and row.next_attempt_at > utcnow()
    registry.rpc_down = False
    await _release_backoff()
    await _pipeline()
    assert (await _row(bounty_id=uuid.UUID(bid))).status == AttestationStatus.CONFIRMED


async def test_backfill_attests_payouts_settled_before_the_feature(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, attestations=False)
    _r, contributor, bid, _payout, _w = await _paid_contribution(client_factory, outbox_mail)
    await drain_events()  # the feature is off: nothing is queued
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(CompletionAttestation.id)) is None
    summary = await client_factory().get(f"/users/{contributor.me['username']}/reputation")  # type: ignore[index]
    assert summary["enabled"] is False and summary["attested_completions"] == 0

    _enable(monkeypatch)
    fake = FakeAttestationChain(reputation_chain.get_config())
    reputation_chain.set_chain(fake)
    try:
        async with get_sessionmaker()() as session:
            assert await reputation_service.backfill(session) == 1
            assert await reputation_service.backfill(session) == 0  # idempotent
        await _pipeline()
        row = await _row(bounty_id=uuid.UUID(bid))
        assert row.status == AttestationStatus.CONFIRMED and len(fake.records) == 1
    finally:
        reputation_chain.set_chain(None)


async def test_reconciliation_flags_drift_and_applies_onchain_revocation(
    client_factory: Any, outbox_mail: Any, registry: FakeAttestationChain
) -> None:
    _r, contributor, bid, _payout, _w = await _paid_contribution(client_factory, outbox_mail)
    username = contributor.me["username"]  # type: ignore[index]
    await drain_events()
    await _pipeline()
    anon = client_factory()
    assert (await anon.get(f"/users/{username}/attestations"))["total"] == 1

    registry.tamper(1, amount=1)  # the chain no longer says what the database says
    async with get_sessionmaker()() as session:
        report = await reputation_service.reconcile(session)
    assert report.checked == 1 and report.mismatched == 1
    assert (await _row(bounty_id=uuid.UUID(bid))).chain_check == ChainCheck.MISMATCH
    assert (await anon.get(f"/users/{username}/attestations"))["total"] == 0  # never shown unless verified
    assert (await anon.get(f"/users/{username}/reputation"))["attested_completions"] == 0

    registry.tamper(1, amount=125_000_000, revoked=True, revoked_at=1, revocation_reason="Revoked elsewhere")
    async with get_sessionmaker()() as session:
        report = await reputation_service.reconcile(session)
    assert report.matching == 1 and report.revoked_on_chain == 1
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.status == AttestationStatus.REVOKED and row.revocation_reason == "Revoked elsewhere"


async def test_admin_revocation_revokes_on_chain_and_credentials(
    client_factory: Any, outbox_mail: Any, db_session: Any, registry: FakeAttestationChain
) -> None:
    _r, contributor, bid, _payout, _w = await _paid_contribution(client_factory, outbox_mail)
    await drain_events()
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    issued = await contributor.post(f"/credentials/completions/{row.id}")
    credential = issued["document"]

    admin = client_factory()
    await register(admin, f"rep_admin_{uuid.uuid4().hex[:6]}")
    moderator = client_factory()
    await register(moderator, f"rep_mod_{uuid.uuid4().hex[:6]}")
    await set_role(db_session, moderator, Role.MODERATOR)
    denied = await moderator.request(
        "POST", f"/admin/attestations/{row.id}/revoke", json={"reason": "Wrong contributor recorded"}
    )
    assert denied.status_code == 403  # revocation needs user:manage (admins)
    await set_role(db_session, admin, Role.ADMIN)
    bad = await admin.request("POST", f"/admin/attestations/{row.id}/revoke", json={"reason": "x"})
    assert bad.status_code == 422

    revoked = await admin.post(
        f"/admin/attestations/{row.id}/revoke", {"reason": "Wrong contributor recorded"}
    )
    assert revoked["status"] == "REVOKED" and revoked["revocation_reason"] == "Wrong contributor recorded"
    assert (
        registry.records[1].revoked and registry.records[1].revocation_reason == "Wrong contributor recorded"
    )
    again = await admin.request("POST", f"/admin/attestations/{row.id}/revoke", json={"reason": "Twice now"})
    assert again.status_code == 409

    anon = client_factory()
    public = await anon.get(f"/users/{contributor.me['username']}/attestations")  # type: ignore[index]
    assert public["items"][0]["status"] == "REVOKED"
    assert (await anon.get(f"/users/{contributor.me['username']}/reputation"))["attested_completions"] == 0  # type: ignore[index]

    report = await anon.post("/credentials/verify", {"credential": credential}, csrf=False)
    checks = {c["id"]: c["status"] for c in report["checks"]}
    assert report["verified"] is False and checks["signature"] == "pass"
    assert checks["status"] == "fail" and checks["attestation"] == "fail"
    status_vc = await anon.get("/credentials/status/revocation")
    index = int(credential["credentialStatus"]["statusListIndex"])
    assert status_list.is_set(status_list.decode(status_vc["credentialSubject"]["encodedList"]), index)

    listed = await admin.get("/admin/attestations", params={"status": "REVOKED"})
    assert listed["total"] == 1 and listed["items"][0]["chain_check"] == "MATCH"


# --- Credentials ----------------------------------------------------------------------------


async def test_credentials_issue_download_and_verify(
    client_factory: Any, outbox_mail: Any, registry: FakeAttestationChain
) -> None:
    _r, contributor, bid, payout, wallet = await _paid_contribution(client_factory, outbox_mail)
    await drain_events()
    anon = client_factory()

    issuer = await anon.get("/credentials/issuer")
    assert issuer["enabled"] is True and issuer["did"] == "did:web:frontend.test"
    did_doc = (await anon.http.get("/.well-known/did.json")).json()
    assert did_doc["id"] == issuer["did"] and did_doc["assertionMethod"] == [issuer["verification_method"]]
    assert did_doc["verificationMethod"][0]["publicKeyMultibase"].startswith("z6Mk")

    row = await _row(bounty_id=uuid.UUID(bid))
    pending = await contributor.request("POST", f"/credentials/completions/{row.id}")
    assert pending.status_code == 409  # only a completion confirmed on-chain
    await _pipeline()
    row = await _row(bounty_id=uuid.UUID(bid))
    assert row.attestation_tx_hash

    other = client_factory()
    await register(other)
    assert (await other.request("POST", f"/credentials/completions/{row.id}")).status_code == 404

    issued = await contributor.post(f"/credentials/completions/{row.id}")
    assert (await contributor.post(f"/credentials/completions/{row.id}"))["id"] == issued["id"]  # idempotent
    vc = issued["document"]
    assert vc["type"] == ["VerifiableCredential", "BountyCompletionCredential"]
    assert vc["issuer"]["id"] == issuer["did"]
    assert vc["credentialSubject"]["id"] == f"did:pkh:stellar:testnet:{wallet}"
    completion = vc["credentialSubject"]["completion"]
    assert (
        completion["payoutTransaction"] == payout["transaction_hash"] and completion["attestation"]["id"] == 1
    )
    assert vc["proof"]["cryptosuite"] == "eddsa-jcs-2022" and vc["proof"]["proofValue"].startswith("z")

    download = await contributor.request("GET", f"/credentials/{issued['id']}/download", expected=200)
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.json() == vc
    assert (await other.request("GET", f"/credentials/{issued['id']}")).status_code == 404
    assert len(await contributor.get("/credentials/me")) == 1

    # Anyone can verify, without a session or CSRF token.
    report = await anon.post("/credentials/verify", {"credential": vc}, csrf=False)
    assert report["verified"] is True, report
    assert [c["status"] for c in report["checks"]] == ["pass"] * 6
    assert report["attestations"][0]["attestation_path"] == "/attestations/1"
    assert report["attestations"][0]["explorer_url"].endswith(row.attestation_tx_hash)

    tampered = copy.deepcopy(vc)
    tampered["credentialSubject"]["completion"]["amount"] = "1250.0000000"
    report = await anon.post("/credentials/verify", {"credential": tampered}, csrf=False)
    checks = {c["id"]: c["status"] for c in report["checks"]}
    assert report["verified"] is False and checks["signature"] == "fail" and checks["attestation"] == "fail"

    forged = copy.deepcopy(vc)
    forged["issuer"]["id"] = "did:web:elsewhere.example"
    report = await anon.post("/credentials/verify", {"credential": forged}, csrf=False)
    assert report["verified"] is False and report["checks"][1]["status"] == "fail"

    junk = await anon.post("/credentials/verify", {"credential": {"hello": "world"}}, csrf=False)
    assert junk["verified"] is False and junk["checks"][0]["status"] == "fail"

    summary = await contributor.post("/credentials/summary")
    assert (await contributor.post("/credentials/summary"))["id"] == summary["id"]  # nothing new to summarise
    reputation = summary["document"]["credentialSubject"]["reputation"]
    assert reputation["completions"] == 1 and reputation["attestations"][0]["id"] == 1
    report = await anon.post("/credentials/verify", {"credential": summary["document"]}, csrf=False)
    assert report["verified"] is True and report["kind"] == "summary"


async def test_credentials_are_off_without_an_issuer_key(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, attestations=False, credentials=False)
    anon = client_factory()
    assert (await anon.get("/credentials/issuer"))["enabled"] is False
    assert (await anon.http.get("/.well-known/did.json")).status_code == 404
    off = await anon.request("POST", "/credentials/verify", json={"credential": {"a": 1}})
    assert off.status_code == 503 and off.json()["error"]["code"] == "credentials_disabled"
    user = client_factory()
    await register(user)
    assert (await user.request("POST", "/credentials/summary")).status_code == 503
