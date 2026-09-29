"""Escrow v2 through the API, against the contract model: milestone releases, the on-chain review clock
(record, answer, claim after the window), batch payouts, and escrows that stay on the v1 contract."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.modules.escrow import chain as escrow_chain
from app.modules.escrow import claims
from app.modules.payments.models import BlockchainTransaction, BountyEscrow
from tests.integration.api.conftest import (
    ApiClient,
    bounty_payload,
    chain_action,
    drain_events,
    link_wallet,
    register,
    sign_xdr,
    verify_email,
)
from tests.support.fake_chain import FakeStellarChain

V1_CONTRACT = "CCJ52FHVMCQUPTOKFKT56DJ6BR5H2552ZAETND3P4Z5S5DGSBCQRLMXK"


@pytest.fixture
def chain_clock(chain: FakeStellarChain, monkeypatch: pytest.MonkeyPatch) -> FakeStellarChain:
    """The backend's review-clock checks follow the fake chain's clock (which tests can advance)."""

    def now() -> datetime:
        return datetime.fromtimestamp(chain.now(), UTC)

    monkeypatch.setattr(escrow_chain, "utcnow", now)
    monkeypatch.setattr(escrow_chain, "_now_ts", chain.now)
    monkeypatch.setattr(claims, "utcnow", now)
    return chain


async def _requester(client_factory: Any, mail: Any) -> tuple[ApiClient, str]:
    client = client_factory()
    await register(client, f"req{uuid.uuid4().hex[:8]}")
    await verify_email(client, mail)
    return client, await link_wallet(client)


async def _contributor(client_factory: Any) -> tuple[ApiClient, str]:
    client = client_factory()
    await register(client, f"dev{uuid.uuid4().hex[:8]}")
    return client, await link_wallet(client)


async def _fund(client: ApiClient, wallet: str, bounty_id: str) -> dict[str, Any]:
    tx = await chain_action(client, f"/bounties/{bounty_id}/funding/prepare", {"wallet_address": wallet})
    return tx


async def _accept_and_assign(
    requester: ApiClient, req_wallet: str, contributor: ApiClient, bounty_id: str
) -> dict[str, Any]:
    application = await contributor.post(
        f"/bounties/{bounty_id}/applications",
        {"cover_message": "I have delivered this kind of work before and can start today."},
        expected=201,
    )
    accepted = await requester.post(f"/applications/{application['id']}/accept", {"note": "Welcome aboard"})
    await chain_action(
        requester,
        f"/bounties/{bounty_id}/chain/prepare",
        {"action": "ASSIGN", "wallet_address": req_wallet, "assignment_id": accepted["assignment_id"]},
    )
    return accepted


async def _submit(contributor: ApiClient, bounty_id: str, **extra: Any) -> dict[str, Any]:
    return await contributor.post(
        f"/bounties/{bounty_id}/submissions",
        {"description": "Delivered the work with tests and a short write-up.", **extra},
        expected=201,
    )


async def test_milestones_are_authored_funded_once_and_paid_one_by_one(
    client_factory: Any, outbox_mail: Any
) -> None:
    requester, req_wallet = await _requester(client_factory, outbox_mail)
    two = [{"title": "Design review", "amount": "4"}, {"title": "Implementation", "amount": "6"}]
    wrong_sum = await requester.request(
        "POST",
        "/bounties",
        json=bounty_payload(reward_amount="10", milestones=[two[0], {**two[1], "amount": "5"}]),
    )
    assert wrong_sum.status_code == 422
    multi = await requester.request(
        "POST", "/bounties", json=bounty_payload(reward_amount="10", positions_available=2, milestones=two)
    )
    assert multi.status_code == 422

    bounty = await requester.post(
        "/bounties", bounty_payload(reward_amount="10", milestones=two), expected=201
    )
    assert [(m["title"], m["amount"], m["status"]) for m in bounty["milestones"]] == [
        ("Design review", "4.0000000", "OPEN"),
        ("Implementation", "6.0000000", "OPEN"),
    ]
    bid = bounty["id"]
    await client_factory().get(f"/bounties/{bid}/milestones", expected=404)  # drafts are private
    await requester.post(f"/bounties/{bid}/publish")
    funding = await _fund(requester, req_wallet, bid)
    assert funding["function_name"] == "create_escrow_v2"
    detail = await requester.get(f"/bounties/{bid}")
    assert detail["escrow"]["contract_version"] == 2 and detail["funding_status"] == "FUNDED"
    locked = await requester.request(
        "PUT",
        f"/bounties/{bid}/milestones",
        json={"milestones": [{"title": "All of it", "amount": "10"}] * 2},
    )
    assert locked.status_code == 409

    contributor, contrib_wallet = await _contributor(client_factory)
    await _accept_and_assign(requester, req_wallet, contributor, bid)
    no_milestone = await contributor.request(
        "POST", f"/bounties/{bid}/submissions", json={"description": "Delivered without naming a milestone."}
    )
    assert no_milestone.status_code == 422
    first = await _submit(contributor, bid, milestone_id=bounty["milestones"][0]["id"])
    assert first["milestone"]["title"] == "Design review"
    again = await contributor.request(
        "POST",
        f"/bounties/{bid}/submissions",
        json={
            "description": "A second submission for the same milestone.",
            "milestone_id": first["milestone"]["id"],
        },
    )
    assert again.status_code == 409
    approved = await requester.post(f"/submissions/{first['id']}/approve", {"feedback": "Looks right"})
    assert approved["payment"]["amount"] == "4.0000000"

    whole = await requester.request(
        "POST",
        f"/bounties/{bid}/payouts/prepare",
        json={"wallet_address": req_wallet, "submission_id": first["id"]},
    )
    assert whole.status_code == 409  # a milestone bounty is paid per milestone
    tx = await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {"action": "MILESTONE_PAYOUT", "wallet_address": req_wallet, "submission_id": first["id"]},
    )
    assert tx["function_name"] == "release_milestone" and tx["amount"] == "4.0000000"
    assert tx["destination_address"] == contrib_wallet
    detail = await requester.get(f"/bounties/{bid}")
    assert [m["status"] for m in detail["milestones"]] == ["PAID", "OPEN"]
    assert detail["milestones"][0]["explorer_url"].endswith(tx["transaction_hash"])
    assert detail["status"] == "IN_PROGRESS" and detail["escrow"]["paid_out_amount"] == "4.0000000"
    assert (await contributor.get(f"/submissions/{first['id']}"))["payment"]["payment_status"] == "CONFIRMED"
    assert (await contributor.get(f"/bounties/{bid}"))["viewer"]["can_submit"] is True

    second = await _submit(contributor, bid, milestone_id=bounty["milestones"][1]["id"])
    await requester.post(f"/submissions/{second['id']}/approve", {"feedback": "Done"})
    await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {"action": "MILESTONE_PAYOUT", "wallet_address": req_wallet, "submission_id": second["id"]},
    )
    final = await requester.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED" and final["escrow"]["paid_out_amount"] == "10.0000000"
    assert [m["status"] for m in final["milestones"]] == ["PAID", "PAID"]

    await drain_events()
    inbox = await contributor.get("/notifications")
    titles = [n["title"] for n in inbox["items"]]
    assert titles.count("Milestone paid") == 2


async def test_unanswered_review_window_lets_the_contributor_claim(
    client_factory: Any, outbox_mail: Any, chain_clock: FakeStellarChain
) -> None:
    requester, req_wallet = await _requester(client_factory, outbox_mail)
    too_short = await requester.request("POST", "/bounties", json=bounty_payload(review_window_seconds=3600))
    assert too_short.status_code == 422
    bounty = await requester.post(
        "/bounties", bounty_payload(reward_amount="8", review_window_seconds=86400), expected=201
    )
    bid = bounty["id"]
    assert bounty["review_window_seconds"] == 86400
    await requester.post(f"/bounties/{bid}/publish")
    assert (await _fund(requester, req_wallet, bid))["function_name"] == "create_escrow_v2"
    contributor, contrib_wallet = await _contributor(client_factory)
    await _accept_and_assign(requester, req_wallet, contributor, bid)
    submission = await _submit(contributor, bid)

    await chain_action(
        contributor,
        f"/bounties/{bid}/chain/prepare",
        {"action": "SUBMIT_WORK", "wallet_address": contrib_wallet, "submission_id": submission["id"]},
    )
    recorded = await contributor.get(f"/submissions/{submission['id']}")
    review = recorded["onchain_review"]
    assert review["state"] == "PENDING" and review["can_claim"] is False and review["can_answer"] is True
    opens = datetime.fromisoformat(review["claimable_at"]).timestamp()
    assert abs(opens - (chain_clock.now() + 86400)) < 5

    # While the clock runs, answers must be signed on-chain.
    offchain = await requester.request(
        "POST", f"/submissions/{submission['id']}/request-revision", json={"feedback": "Please add tests."}
    )
    assert offchain.status_code == 409 and offchain.json()["error"]["code"] == "onchain_review_pending"
    early = await contributor.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "CLAIM", "wallet_address": contrib_wallet, "submission_id": submission["id"]},
    )
    assert early.status_code == 409

    chain_clock.advance_time(86400)
    async with get_sessionmaker()() as session:
        assert await claims.mark_claimable(session) == 1
    async with get_sessionmaker()() as session:
        assert await claims.mark_claimable(session) == 0  # marked once
    await drain_events()
    titles = [n["title"] for n in (await contributor.get("/notifications"))["items"]]
    assert "Payment ready to claim" in titles
    late = await requester.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={
            "action": "REQUEST_CHANGES",
            "wallet_address": req_wallet,
            "submission_id": submission["id"],
            "feedback": "Please add tests.",
        },
    )
    assert late.status_code == 409  # the window passed

    tx = await chain_action(
        contributor,
        f"/bounties/{bid}/chain/prepare",
        {"action": "CLAIM", "wallet_address": contrib_wallet, "submission_id": submission["id"]},
    )
    assert tx["function_name"] == "claim" and tx["amount"] == "8.0000000"
    paid = await contributor.get(f"/submissions/{submission['id']}")
    assert paid["status"] == "APPROVED" and paid["payment"]["payment_status"] == "CONFIRMED"
    assert paid["onchain_review"]["state"] == "PAID"
    final = await requester.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED" and final["funding_status"] == "SETTLED"


async def test_onchain_answers_stop_the_clock_and_mirror_the_review(
    client_factory: Any, outbox_mail: Any, chain_clock: FakeStellarChain
) -> None:
    requester, req_wallet = await _requester(client_factory, outbox_mail)
    bounty = await requester.post("/bounties", bounty_payload(review_window_seconds=86400), expected=201)
    bid = bounty["id"]
    await requester.post(f"/bounties/{bid}/publish")
    await _fund(requester, req_wallet, bid)
    contributor, contrib_wallet = await _contributor(client_factory)
    await _accept_and_assign(requester, req_wallet, contributor, bid)
    submission = await _submit(contributor, bid)
    record = {"action": "SUBMIT_WORK", "wallet_address": contrib_wallet, "submission_id": submission["id"]}
    await chain_action(contributor, f"/bounties/{bid}/chain/prepare", record)

    no_feedback = await requester.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "REQUEST_CHANGES", "wallet_address": req_wallet, "submission_id": submission["id"]},
    )
    assert no_feedback.status_code == 422
    await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {
            "action": "REQUEST_CHANGES",
            "wallet_address": req_wallet,
            "submission_id": submission["id"],
            "feedback": "Please cover the error states too.",
        },
    )
    revised = await contributor.get(f"/submissions/{submission['id']}")
    assert revised["status"] == "REVISION_REQUESTED"
    assert revised["review_feedback"] == "Please cover the error states too."
    assert revised["onchain_review"]["state"] == "CHANGES_REQUESTED"

    await contributor.patch(
        f"/submissions/{submission['id']}", {"description": "Delivered again with the error states covered."}
    )
    await chain_action(contributor, f"/bounties/{bid}/chain/prepare", record)
    await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {
            "action": "REJECT_SUBMISSION",
            "wallet_address": req_wallet,
            "submission_id": submission["id"],
            "feedback": "This does not meet the acceptance criteria.",
        },
    )
    rejected = await contributor.get(f"/submissions/{submission['id']}")
    assert rejected["status"] == "REJECTED" and rejected["onchain_review"]["state"] == "REJECTED"
    # The contributor stays assigned on-chain, so they can still raise a dispute.
    detail = await contributor.get(f"/bounties/{bid}")
    assert detail["viewer"]["is_assigned"] is True
    again = await contributor.request("POST", f"/bounties/{bid}/chain/prepare", json=record)
    assert again.status_code == 409


async def test_batch_payout_pays_every_contributor_in_one_transaction(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    requester, req_wallet = await _requester(client_factory, outbox_mail)
    bounty = await requester.post(
        "/bounties", bounty_payload(reward_amount="5", positions_available=2), expected=201
    )
    bid = bounty["id"]
    await requester.post(f"/bounties/{bid}/publish")
    assert (await _fund(requester, req_wallet, bid))["function_name"] == "create_escrow"  # plain v1 terms
    submissions = []
    for _ in range(2):
        contributor, _wallet = await _contributor(client_factory)
        await _accept_and_assign(requester, req_wallet, contributor, bid)
        submission = await _submit(contributor, bid)
        await requester.post(f"/submissions/{submission['id']}/approve", {"feedback": "Good"})
        submissions.append(submission["id"])

    one = await requester.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "BATCH_PAYOUT", "wallet_address": req_wallet, "submission_ids": submissions[:1]},
    )
    assert one.status_code == 422

    # A batch that fails on-chain leaves every payment unpaid (and payable again).
    chain.fail_next_execution = 7
    prepared = await requester.post(
        f"/bounties/{bid}/chain/prepare",
        {"action": "BATCH_PAYOUT", "wallet_address": req_wallet, "submission_ids": submissions},
    )
    signed = sign_xdr(prepared["unsigned_xdr"], req_wallet)
    failed = await requester.post(
        f"/transactions/{prepared['transaction']['id']}/submit", {"signed_xdr": signed}
    )
    assert failed["status"] == "FAILED"
    for sid in submissions:
        assert (await requester.get(f"/submissions/{sid}"))["payment"]["payment_status"] == "FAILED"

    tx = await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {"action": "BATCH_PAYOUT", "wallet_address": req_wallet, "submission_ids": submissions},
    )
    assert tx["function_name"] == "batch_release" and tx["amount"] == "10.0000000"
    for sid in submissions:
        payment = (await requester.get(f"/submissions/{sid}"))["payment"]
        assert payment["payment_status"] == "CONFIRMED"
        assert payment["transaction"]["transaction_hash"] == tx["transaction_hash"]
    final = await requester.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED" and final["escrow"]["paid_out_amount"] == "10.0000000"


async def test_escrows_on_the_v1_contract_keep_their_contract(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    requester, req_wallet = await _requester(client_factory, outbox_mail)
    bounty = await requester.post("/bounties", bounty_payload(), expected=201)
    bid = bounty["id"]
    await requester.post(f"/bounties/{bid}/publish")
    funding = await _fund(requester, req_wallet, bid)
    # The escrow row as it looks for escrows created before v2 (backfilled by migration 0007).
    await db_session.execute(
        update(BountyEscrow)
        .where(BountyEscrow.bounty_id == uuid.UUID(bid))
        .values(contract_id=V1_CONTRACT, contract_version=1)
    )
    # The creation was prepared for that contract too.
    await db_session.execute(
        update(BlockchainTransaction)
        .where(BlockchainTransaction.id == uuid.UUID(funding["id"]))
        .values(contract_id=V1_CONTRACT)
    )
    await db_session.commit()
    contributor, contrib_wallet = await _contributor(client_factory)
    application = await contributor.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "I have delivered this kind of work before and can start today."},
        expected=201,
    )
    accepted = await requester.post(f"/applications/{application['id']}/accept", {"note": "Welcome aboard"})
    assign = await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {"action": "ASSIGN", "wallet_address": req_wallet, "assignment_id": accepted["assignment_id"]},
    )
    assert assign["contract_id"] == V1_CONTRACT
    submission = await _submit(contributor, bid)
    record = await contributor.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "SUBMIT_WORK", "wallet_address": contrib_wallet, "submission_id": submission["id"]},
    )
    assert record.status_code == 409 and "v1 contract" in record.json()["error"]["message"]
    await requester.post(f"/submissions/{submission['id']}/approve", {"feedback": "Good"})
    payout = await chain_action(
        requester,
        f"/bounties/{bid}/payouts/prepare",
        {"wallet_address": req_wallet, "submission_id": submission["id"]},
    )
    assert payout["contract_id"] == V1_CONTRACT and payout["function_name"] == "release"
    assert (await requester.get(f"/bounties/{bid}"))["status"] == "COMPLETED"


async def test_escrow_config_is_public(client_factory: Any) -> None:
    config = await client_factory().get("/escrow/config")
    assert config["contract_version"] == 2
    assert config["min_review_window_seconds"] == 86400 and config["default_review_window_seconds"] == 604800
    assert config["arbiter_threshold"] == 1 and len(config["arbiter_addresses"]) == 1
    assert config["max_batch"] == 10
