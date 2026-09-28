"""Opt-in end-to-end test against the REAL Stellar Testnet and a running API.

    RUN_TESTNET_E2E=1 API_BASE_URL=http://localhost:8000 uv run pytest tests/contract/test_testnet_flow.py -m testnet -s

Requirements: the API is running in BLOCKCHAIN_MODE=testnet with the escrow contract configured, the database is
seeded (`make seed`; sign-in password from SEED_USER_PASSWORD), and Friendbot is reachable. Two throwaway keypairs are generated and
funded by Friendbot; they stand in for browser wallets by signing the exact XDR the API prepares. Nothing here is
mocked: every transaction is submitted to Testnet and verified by the backend from chain state.

Ordinary CI never runs this (it needs network access and Friendbot).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from stellar_sdk import Keypair, Network, TransactionEnvelope

pytestmark = [
    pytest.mark.testnet,
    pytest.mark.skipif(os.environ.get("RUN_TESTNET_E2E") != "1", reason="set RUN_TESTNET_E2E=1 to run"),
]

API = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/") + "/api/v1"
PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE


class Client:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(base_url=API, timeout=60)

    def _csrf(self) -> dict[str, str]:
        token = self.http.cookies.get("bf_csrf")
        return {"X-CSRF-Token": token} if token else {}

    async def call(
        self, method: str, path: str, expected: int | tuple[int, ...] = (200, 201, 204), **kw: object
    ) -> dict:
        response = await self.http.request(method, path, headers=self._csrf(), **kw)  # type: ignore[arg-type]
        codes = expected if isinstance(expected, tuple) else (expected,)
        assert response.status_code in codes, f"{method} {path} -> {response.status_code}: {response.text}"
        return response.json() if response.content else {}

    async def close(self) -> None:
        await self.http.aclose()


async def _friendbot(address: str) -> None:
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.get("https://friendbot.stellar.org", params={"addr": address})
        assert r.status_code in (200, 400), r.text  # 400 = already funded


async def _link_wallet(client: Client, kp: Keypair) -> None:
    challenge = await client.call("POST", "/wallets/challenge", json={"public_address": kp.public_key})
    env = TransactionEnvelope.from_xdr(challenge["challenge_xdr"], PASSPHRASE)
    env.sign(kp)
    wallet = await client.call(
        "POST",
        "/wallets/verify",
        json={"public_address": kp.public_key, "signed_challenge_xdr": env.to_xdr()},
    )
    assert wallet["verification_status"] == "VERIFIED" and wallet["network"] == "testnet"


async def _sign_and_submit(client: Client, prepared: dict, kp: Keypair) -> dict:
    assert prepared["network"] == "testnet" and prepared["unsigned_xdr"]
    env = TransactionEnvelope.from_xdr(prepared["unsigned_xdr"], PASSPHRASE)
    env.sign(kp)
    tx = await client.call(
        "POST", f"/transactions/{prepared['transaction']['id']}/submit", json={"signed_xdr": env.to_xdr()}
    )
    for _ in range(45):
        if tx["status"] in ("CONFIRMED", "FAILED", "EXPIRED"):
            break
        await asyncio.sleep(2)
        tx = await client.call("GET", f"/transactions/{tx['id']}")
    assert tx["status"] == "CONFIRMED", tx
    assert tx["explorer_url"] and tx["transaction_hash"] in tx["explorer_url"]
    return tx


async def test_full_bounty_lifecycle_on_testnet() -> None:
    requester_kp, contributor_kp = Keypair.random(), Keypair.random()
    await asyncio.gather(_friendbot(requester_kp.public_key), _friendbot(contributor_kp.public_key))

    requester, contributor = Client(), Client()
    try:
        password = os.environ.get("SEED_USER_PASSWORD", "BountyFlow!2026")
        await requester.call(
            "POST", "/auth/login", json={"email": "ada.okafor@bountyflow.test", "password": password}
        )
        await contributor.call(
            "POST", "/auth/login", json={"email": "kai.tanaka@bountyflow.test", "password": password}
        )
        await _link_wallet(requester, requester_kp)
        await _link_wallet(contributor, contributor_kp)

        deadline = datetime.now(UTC) + timedelta(days=10)
        bounty = await requester.call(
            "POST",
            "/bounties",
            json={
                "title": f"Testnet E2E bounty {uuid.uuid4().hex[:6]}",
                "short_description": "Automated end-to-end verification of the escrow lifecycle on Testnet.",
                "description": "This bounty is created by the automated Testnet integration test suite. " * 2,
                "category": "DEVELOPMENT",
                "difficulty": "BEGINNER",
                "reward_amount": "1.5",
                "positions_available": 1,
                "tags": ["e2e"],
                "required_skills": ["testing"],
                "application_deadline": (deadline - timedelta(days=5)).isoformat(),
                "completion_deadline": deadline.isoformat(),
            },
        )
        bid = bounty["id"]
        await requester.call("POST", f"/bounties/{bid}/publish")

        # Fund: create_escrow + deposit, signed by the requester's wallet, verified from chain.
        prepared = await requester.call(
            "POST", f"/bounties/{bid}/funding/prepare", json={"wallet_address": requester_kp.public_key}
        )
        assert prepared["summary"]["function_name"] == "create_escrow"
        await _sign_and_submit(requester, prepared, requester_kp)
        detail = await requester.call("GET", f"/bounties/{bid}")
        assert detail["status"] == "FUNDED" and detail["funding_status"] == "FUNDED"
        assert detail["escrow"]["funded_amount"] == "1.5000000"

        application = await contributor.call(
            "POST",
            f"/bounties/{bid}/applications",
            json={"cover_message": "I will complete this automated task promptly and carefully."},
        )
        await requester.call("POST", f"/applications/{application['id']}/accept", json={"note": "Welcome"})

        submission = await contributor.call(
            "POST",
            f"/bounties/{bid}/submissions",
            json={
                "description": "Completed the task; evidence attached for automated verification.",
                "evidence_url": "https://github.com/stellar",
            },
        )
        await requester.call(
            "POST",
            f"/submissions/{submission['id']}/request-revision",
            json={"feedback": "Please add more detail."},
        )
        await contributor.call(
            "PATCH",
            f"/submissions/{submission['id']}",
            json={"description": "Completed the task with the requested extra detail included."},
        )
        approved = await requester.call(
            "POST", f"/submissions/{submission['id']}/approve", json={"feedback": "Great"}
        )
        assert approved["payment"]["payment_status"] == "CREATED"

        payout = await requester.call(
            "POST",
            f"/bounties/{bid}/payouts/prepare",
            json={"wallet_address": requester_kp.public_key, "submission_id": submission["id"]},
        )
        assert payout["summary"]["function_name"] == "release"
        await _sign_and_submit(requester, payout, requester_kp)

        final = await requester.call("GET", f"/bounties/{bid}")
        assert final["status"] == "COMPLETED"
        assert final["escrow"]["state"] == "COMPLETED"
        assert final["escrow"]["paid_out_amount"] == "1.5000000"
        paid = await contributor.call("GET", f"/submissions/{submission['id']}")
        assert paid["payment"]["payment_status"] == "CONFIRMED"

        # Duplicate payout attempts are rejected (DB state + contract AlreadyPaid).
        await requester.call(
            "POST",
            f"/bounties/{bid}/payouts/prepare",
            expected=(409, 422),
            json={"wallet_address": requester_kp.public_key, "submission_id": submission["id"]},
        )
    finally:
        await requester.close()
        await contributor.close()
