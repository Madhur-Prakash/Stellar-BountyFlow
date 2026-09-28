"""Redis is an optimisation, not a security boundary.

Transaction locks and rate limits fail *open* when Redis is down; the database (row locks + unique constraints)
and the contract must still prevent any double effect. Wallet challenges fail *closed*.
"""

from __future__ import annotations

import asyncio
from typing import Any

from stellar_sdk import Keypair, TransactionEnvelope
from stellar_sdk.sep.stellar_web_authentication import build_challenge_transaction

from app.blockchain.config import get_network
from app.blockchain.wallet import WEB_AUTH_DOMAIN
from app.cache import redis as cache_redis
from app.core.config import get_settings
from tests.integration.api.conftest import sign_xdr
from tests.integration.security.helpers import assigned_contributor, funded, new_requester, new_user
from tests.support.fake_chain import FakeStellarChain


class BrokenRedis:
    """Every command fails as if the Redis server were unreachable."""

    def __getattr__(self, name: str) -> Any:
        raise ConnectionError("redis unavailable")


async def test_double_submit_with_redis_down_settles_once(
    client_factory: Any, outbox_mail: Any, fake_redis: Any, chain: FakeStellarChain
) -> None:
    requester, wallet = await new_requester(client_factory, outbox_mail, "redisdown")
    bounty = await funded(requester, wallet, reward_amount="8")
    bid = bounty["id"]
    contributor, contributor_wallet, _accepted = await assigned_contributor(client_factory, requester, bid)
    submission = await contributor.post(
        f"/bounties/{bid}/submissions",
        {"description": "Complete delivery with tests and docs."},
        expected=201,
    )
    await requester.post(f"/submissions/{submission['id']}/approve", {})
    prepared = await requester.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": submission["id"]}
    )
    tx_id = prepared["transaction"]["id"]
    body = {"signed_xdr": sign_xdr(prepared["unsigned_xdr"], wallet)}

    calls_before = chain.submit_calls
    chain.submit_latency = 0.05  # widen the race window
    cache_redis.set_redis(BrokenRedis())  # type: ignore[arg-type]
    try:
        results = await asyncio.gather(
            *[requester.request("POST", f"/transactions/{tx_id}/submit", json=body) for _ in range(3)]
        )
    finally:
        cache_redis.set_redis(fake_redis)
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert chain.submit_calls - calls_before == 1, "the transaction was sent to the network more than once"

    final = await requester.get(f"/bounties/{bid}")
    assert final["escrow"]["paid_out_amount"] == "8.0000000"
    paid = await contributor.get(f"/submissions/{submission['id']}")
    assert paid["payment"]["payment_status"] == "CONFIRMED"
    assert paid["payment"]["transaction"]["destination_address"] == contributor_wallet


async def test_wallet_challenges_fail_closed_without_redis(client_factory: Any, fake_redis: Any) -> None:
    user = await new_user(client_factory, "noredis")
    keypair = Keypair.random()
    address = keypair.public_key
    # A well-formed, genuinely signed SEP-10 envelope: without Redis it can't be checked against an issued
    # challenge, so it must not be accepted.
    challenge_xdr = build_challenge_transaction(
        server_secret=Keypair.random().secret,
        client_account_id=address,
        home_domain=get_settings().wallet_challenge_home_domain,
        web_auth_domain=WEB_AUTH_DOMAIN,
        network_passphrase=get_network().passphrase,
        timeout=300,
    )
    envelope = TransactionEnvelope.from_xdr(challenge_xdr, get_network().passphrase)
    envelope.sign(keypair)
    cache_redis.set_redis(BrokenRedis())  # type: ignore[arg-type]
    try:
        challenge = await user.request("POST", "/wallets/challenge", json={"public_address": address})
        verify = await user.request(
            "POST",
            "/wallets/verify",
            json={"public_address": address, "signed_challenge_xdr": envelope.to_xdr()},
        )
    finally:
        cache_redis.set_redis(fake_redis)
    assert challenge.status_code == 503
    assert verify.status_code == 503
    assert await user.get("/wallets") == []
