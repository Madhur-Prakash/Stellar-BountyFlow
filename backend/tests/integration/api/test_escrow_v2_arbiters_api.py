"""2-of-3 arbiter resolution of a frozen escrow: moderators vote with their own verified arbiter wallets, the
panel shows "n of 2", and the split executes once the second matching approval is confirmed."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import Keypair

from app.blockchain import transactions as chain_module
from app.blockchain.config import get_network
from app.core.config import get_settings
from app.modules.users.models import Role
from tests.integration.api.conftest import (
    API_ENV,
    ApiClient,
    bounty_payload,
    chain_action,
    drain_events,
    link_wallet,
    register,
    verify_email,
)
from tests.integration.security.helpers import set_role
from tests.support.fake_chain import FakeStellarChain

ARBITERS = [
    Keypair.from_raw_ed25519_seed(hashlib.sha256(f"bf-test-arbiter-{n}".encode()).digest()) for n in range(3)
]


@pytest.fixture
async def chain(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeStellarChain]:
    """The API test chain, configured with a 2-of-3 arbiter set."""
    for key, value in API_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("STELLAR_ARBITER_ADDRESS", ARBITERS[0].public_key)
    monkeypatch.setenv("STELLAR_ARBITER_ADDRESSES", ",".join(k.public_key for k in ARBITERS))
    monkeypatch.setenv("STELLAR_ARBITER_THRESHOLD", "2")
    get_settings.cache_clear()
    get_network.cache_clear()
    fake = FakeStellarChain(get_network())
    chain_module.set_adapter(fake)
    try:
        yield fake
    finally:
        get_settings.cache_clear()
        get_network.cache_clear()
        chain_module.set_adapter(None)


async def _user(
    client_factory: Any, mail: Any | None = None, keypair: Keypair | None = None
) -> tuple[ApiClient, str]:
    client = client_factory()
    await register(client, f"u{uuid.uuid4().hex[:10]}")
    if mail is not None:
        await verify_email(client, mail)
    return client, await link_wallet(client, keypair)


async def test_two_of_three_arbiters_execute_a_split(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain, db_session: AsyncSession
) -> None:
    requester, req_wallet = await _user(client_factory, outbox_mail)
    bounty = await requester.post("/bounties", bounty_payload(reward_amount="10"), expected=201)
    bid = bounty["id"]
    await requester.post(f"/bounties/{bid}/publish")
    funding = await chain_action(
        requester, f"/bounties/{bid}/funding/prepare", {"wallet_address": req_wallet}
    )
    assert funding["function_name"] == "create_escrow_v2"
    detail = await requester.get(f"/bounties/{bid}")
    assert detail["escrow"]["arbiter_threshold"] == 2
    assert detail["escrow"]["arbiter_addresses"] == [k.public_key for k in ARBITERS]

    contributor, contrib_wallet = await _user(client_factory)
    application = await contributor.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "I have delivered this kind of work before and can start today."},
        expected=201,
    )
    accepted = await requester.post(f"/applications/{application['id']}/accept", {"note": "Welcome"})
    await chain_action(
        requester,
        f"/bounties/{bid}/chain/prepare",
        {"action": "ASSIGN", "wallet_address": req_wallet, "assignment_id": accepted["assignment_id"]},
    )
    await contributor.post(
        f"/bounties/{bid}/submissions",
        {"description": "Delivered most of the scope; the export is missing."},
        expected=201,
    )
    dispute = await contributor.post(
        f"/bounties/{bid}/disputes",
        {"reason": "The requester stopped answering after the delivery."},
        expected=201,
    )
    await chain_action(
        contributor,
        f"/bounties/{bid}/chain/prepare",
        {"action": "RAISE_DISPUTE", "wallet_address": contrib_wallet, "dispute_id": dispute["id"]},
    )

    moderators = []
    for keypair, role in ((ARBITERS[1], Role.MODERATOR), (ARBITERS[2], Role.ADMIN)):
        mod, wallet = await _user(client_factory, keypair=keypair)
        await set_role(db_session, mod, role)
        moderators.append((mod, wallet))
    (mod_a, wallet_a), (mod_b, wallet_b) = moderators

    too_much = await mod_a.request(
        "POST",
        f"/disputes/{dispute['id']}/resolve",
        json={"resolution": "SPLIT", "note": "Most of the scope was delivered.", "contributor_amount": "10"},
    )
    assert too_much.status_code == 422
    resolved = await mod_a.post(
        f"/disputes/{dispute['id']}/resolve",
        {"resolution": "SPLIT", "note": "Most of the scope was delivered.", "contributor_amount": "7"},
    )
    assert resolved["requires_onchain_execution"] is True and resolved["arbiter_threshold"] == 2

    panel = await mod_a.get(f"/disputes/{dispute['id']}/arbitration")
    assert panel["threshold"] == 2 and panel["approvals"] == 0 and panel["can_vote"] is True
    assert panel["contributor_amount"] == "7.0000000" and panel["requester_amount"] == "3.0000000"
    assert panel["my_arbiter_wallets"] == [wallet_a]

    # The requester's wallet is not an arbiter; RESOLVE_DISPUTE needs every approval, so it is refused.
    single = await mod_a.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "RESOLVE_DISPUTE", "wallet_address": wallet_a, "dispute_id": dispute["id"]},
    )
    assert single.status_code == 409

    vote = {"action": "DISPUTE_VOTE", "dispute_id": dispute["id"]}
    first = await chain_action(mod_a, f"/bounties/{bid}/chain/prepare", {**vote, "wallet_address": wallet_a})
    assert first["function_name"] == "vote_resolution"
    panel = await mod_b.get(f"/disputes/{dispute['id']}/arbitration")
    assert panel["approvals"] == 1 and panel["executed"] is False
    assert [a["approved"] for a in panel["arbiters"]] == [False, True, False]
    assert (await requester.get(f"/bounties/{bid}"))["status"] == "DISPUTED"
    listed = await mod_b.get(f"/disputes/{dispute['id']}")
    assert listed["arbiter_approvals"] == 1

    # One vote per staff account, even with a second arbiter wallet.
    mine_again = await mod_a.get(f"/disputes/{dispute['id']}/arbitration")
    assert mine_again["can_vote"] is False and mine_again["my_vote_recorded"] is True

    await chain_action(mod_b, f"/bounties/{bid}/chain/prepare", {**vote, "wallet_address": wallet_b})
    final = await requester.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED"
    assert (
        final["escrow"]["paid_out_amount"] == "7.0000000"
        and final["escrow"]["refunded_amount"] == "3.0000000"
    )
    panel = await requester.get(f"/disputes/{dispute['id']}/arbitration")
    assert panel["executed"] is True and panel["approvals"] == 2
    payments = await contributor.get("/payments/me")
    assert (
        payments["items"][0]["amount"] == "7.0000000"
        and payments["items"][0]["payment_status"] == "CONFIRMED"
    )

    await drain_events()
    titles = [n["title"] for n in (await contributor.get("/notifications"))["items"]]
    assert "Arbiter approval recorded" in titles and "Dispute decision executed" in titles
