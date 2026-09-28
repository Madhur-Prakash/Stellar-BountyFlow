"""Escrow authenticity and on-chain dispute/assignment safety.

The escrow contract is public: anyone can call ``create_escrow`` with any bounty id, token, arbiter and deadline.
The backend must therefore never adopt an on-chain escrow it did not prepare itself (SEC-01), must not let the
escrow id of a bounty be squatted (SEC-02), and must never let a chain action lock funds irrecoverably (SEC-05,
SEC-06). Direct-to-chain calls (a wallet signing and submitting straight to the network, bypassing BountyFlow) are
modelled with ``FakeStellarChain.invoke_directly``.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from stellar_sdk import StrKey

from app.blockchain import soroban
from app.blockchain.config import get_network
from app.core.money import to_stroops
from app.modules.users.models import Role
from tests.integration.api.conftest import chain_action, link_wallet, sign_xdr
from tests.integration.security.helpers import (
    assigned_contributor,
    funded,
    new_requester,
    new_user,
    published,
    set_role,
)
from tests.support.fake_chain import FakeStellarChain


async def _prepare_unsigned_create(requester: Any, bounty_id: str, wallet: str) -> str:
    """Requester asks BountyFlow to prepare the escrow creation but never signs it. Returns the escrow id."""
    prepared = await requester.post(f"/bounties/{bounty_id}/funding/prepare", {"wallet_address": wallet})
    assert prepared["summary"]["function_name"] == "create_escrow"
    public = await requester.get(f"/bounties/{bounty_id}")
    return str(public["escrow"]["onchain_bounty_id"])


async def test_foreign_token_escrow_is_never_adopted(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    """SEC-01: a requester creates the bounty's escrow directly on-chain with a worthless token (and a tiny
    deposit), then uses BountyFlow's FUND flow to 'top it up'. The backend must not adopt that escrow: otherwise
    the bounty shows as FUNDED and later payouts are recorded as CONFIRMED XLM although only fake tokens moved."""
    requester, wallet = await new_requester(client_factory, outbox_mail, "faketoken")
    bounty = await published(requester, reward_amount="10")
    bid = bounty["id"]
    escrow_id = await _prepare_unsigned_create(requester, bid, wallet)
    network = get_network()

    worthless_token = StrKey.encode_contract(os.urandom(32))
    chain.invoke_directly(
        soroban.create_escrow(
            wallet,
            bytes.fromhex(escrow_id),
            worthless_token,
            to_stroops(Decimal("10")),
            1,
            network.arbiter_address or "",
            int(time.time())
            + 3600,  # a short deadline would also let the requester refund around assignments
            1,
        ),
        wallet,
    )

    second = await requester.post(f"/bounties/{bid}/funding/prepare", {"wallet_address": wallet})
    # The foreign escrow is ignored: BountyFlow creates a fresh escrow (new id) with the configured asset.
    assert second["summary"]["function_name"] == "create_escrow", second["summary"]
    tx = await requester.post(
        f"/transactions/{second['transaction']['id']}/submit",
        {"signed_xdr": sign_xdr(second["unsigned_xdr"], wallet)},
    )
    assert (await requester.get(f"/transactions/{tx['id']}"))["status"] == "CONFIRMED"

    detail = await requester.get(f"/bounties/{bid}")
    assert detail["status"] == "FUNDED"
    assert detail["escrow"]["onchain_bounty_id"] != escrow_id
    snapshot = await chain.read_escrow(bytes.fromhex(detail["escrow"]["onchain_bounty_id"]))
    assert snapshot is not None
    assert snapshot.token == network.native_asset_contract_id
    assert snapshot.arbiter == network.arbiter_address


async def test_squatted_escrow_id_does_not_block_funding(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    """SEC-02: escrow ids must be unpredictable, and a third party who front-runs ``create_escrow`` at a bounty's
    escrow id must not be able to block the real requester from funding (griefing / denial of service)."""
    requester, wallet = await new_requester(client_factory, outbox_mail, "squat")
    bounty = await published(requester, reward_amount="5")
    bid = bounty["id"]
    escrow_id = await _prepare_unsigned_create(requester, bid, wallet)
    predictable = hashlib.sha256(b"bountyflow:bounty:" + uuid.UUID(bid).bytes).hexdigest()
    assert escrow_id != predictable, "escrow ids must not be derivable from the public bounty id"

    squatter = await new_user(client_factory, "squatter")
    squatter_wallet = await link_wallet(squatter)
    network = get_network()
    chain.invoke_directly(
        soroban.create_escrow(
            squatter_wallet,
            bytes.fromhex(escrow_id),
            network.native_asset_contract_id or "",
            to_stroops(Decimal("5")),
            1,
            network.arbiter_address or "",
            int(time.time()) + 86400,
            0,
        ),
        squatter_wallet,
    )

    await chain_action(requester, f"/bounties/{bid}/funding/prepare", {"wallet_address": wallet})
    detail = await requester.get(f"/bounties/{bid}")
    assert detail["status"] == "FUNDED" and detail["funding_status"] == "FUNDED"
    assert detail["escrow"]["onchain_bounty_id"] != escrow_id


async def test_reconcile_refuses_unverified_escrow(
    client_factory: Any, outbox_mail: Any, db_session: Any, chain: FakeStellarChain
) -> None:
    """SEC-01: reconciliation trusts chain state only when the escrow is the one BountyFlow prepared. A foreign
    escrow sitting at the bounty's id (here fully 'funded' by a third party) must not overwrite the DB view."""
    requester, wallet = await new_requester(client_factory, outbox_mail, "recon")
    bounty = await published(requester, reward_amount="3")
    bid = bounty["id"]
    escrow_id = await _prepare_unsigned_create(requester, bid, wallet)

    squatter = await new_user(client_factory, "recon_squat")
    squatter_wallet = await link_wallet(squatter)
    network = get_network()
    chain.invoke_directly(
        soroban.create_escrow(
            squatter_wallet,
            bytes.fromhex(escrow_id),
            network.native_asset_contract_id or "",
            to_stroops(Decimal("3")),
            1,
            network.arbiter_address or "",
            int(time.time()) + 86400,
            to_stroops(Decimal("3")),
        ),
        squatter_wallet,
    )

    moderator = await new_user(client_factory, "recon_mod")
    await set_role(db_session, moderator, Role.MODERATOR)
    response = await moderator.request("POST", f"/admin/bounties/{bid}/reconcile")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "escrow_unverified"
    detail = await requester.get(f"/bounties/{bid}")
    assert detail["funding_status"] in ("UNFUNDED", "PENDING")
    assert detail["escrow"]["funded_amount"] == "0.0000000"


async def test_onchain_dispute_requires_onchain_assignment(client_factory: Any, outbox_mail: Any) -> None:
    """SEC-05: freezing the escrow on-chain when the disputed contributor is not assigned on-chain leaves the
    arbiter nothing to resolve: the contract has no other exit from Disputed, so the funds would be locked
    forever. The backend must refuse to prepare such a RAISE_DISPUTE."""
    requester, wallet = await new_requester(client_factory, outbox_mail, "lock")
    bounty = await funded(requester, wallet, reward_amount="4")
    bid = bounty["id"]
    contributor, _cw, _accepted = await assigned_contributor(client_factory, requester, bid, "lock_c")
    dispute = await contributor.post(
        f"/bounties/{bid}/disputes",
        {"reason": "The requester stopped responding after I started the work."},
        expected=201,
    )
    response = await requester.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "RAISE_DISPUTE", "wallet_address": wallet, "dispute_id": dispute["id"]},
    )
    assert response.status_code == 409, response.text
    detail = await requester.get(f"/bounties/{bid}")
    assert detail["escrow"]["state"] == "FUNDED"


async def test_onchain_assignment_after_deadline_is_refused(
    client_factory: Any, outbox_mail: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-06: after the escrow deadline an on-chain assignment no longer blocks a refund, so recording one would
    give the contributor a false sense of protection. The backend refuses it."""
    requester, wallet = await new_requester(client_factory, outbox_mail, "late")
    bounty = await funded(requester, wallet, reward_amount="2")
    bid = bounty["id"]
    _contributor, _cw, accepted = await assigned_contributor(client_factory, requester, bid, "late_c")

    from app.core.security import utcnow as real_utcnow
    from app.modules.payments import service as payments_service

    monkeypatch.setattr(payments_service, "utcnow", lambda: real_utcnow() + timedelta(days=400))
    response = await requester.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "ASSIGN", "wallet_address": wallet, "assignment_id": accepted["assignment_id"]},
    )
    assert response.status_code == 409, response.text
