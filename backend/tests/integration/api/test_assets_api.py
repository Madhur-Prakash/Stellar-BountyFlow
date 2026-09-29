"""Reward assets end to end: the registry, USDC bounties, funding guards, trustlines added through the wallet-signed
flow, assignment and payout guards with contributor notices, per-asset analytics, and admin asset management with a
Stellar Asset Contract deployment.

Chain calls run against FakeStellarChain (escrow) and FakeLedger (Horizon accounts, trustlines and SACs); both build
and check real transaction envelopes signed with real keypairs. Wallet ownership is inserted directly: the SEP-10
proof itself is covered by the wallet tests.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import update
from stellar_sdk import Keypair

from app.blockchain.assets import sac_contract_id
from app.blockchain.config import get_network
from app.core.exceptions import ValidationFailed
from app.db.session import get_sessionmaker
from app.modules.users.models import Role, User, Wallet, WalletVerificationStatus
from tests.integration.api.conftest import (
    KEYRING,
    ApiClient,
    bounty_payload,
    chain_action,
    drain_events,
    register,
    sign_xdr,
    verify_email,
)
from tests.support.fake_chain import FakeStellarChain
from tests.support.fake_ledger import TESTNET_USDC, FakeLedger

USDC_SAC = "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"


async def own_wallet(client: ApiClient, keypair: Keypair | None = None) -> str:
    kp = keypair or Keypair.random()
    KEYRING[kp.public_key] = kp
    assert client.me is not None
    async with get_sessionmaker()() as session:
        session.add(
            Wallet(
                user_id=uuid.UUID(client.me["id"]),
                public_address=kp.public_key,
                network="testnet",
                verification_status=WalletVerificationStatus.VERIFIED,
            )
        )
        await session.commit()
    return kp.public_key


async def make_admin(client: ApiClient) -> None:
    assert client.me is not None
    async with get_sessionmaker()() as session:
        await session.execute(
            update(User).where(User.id == uuid.UUID(client.me["id"])).values(role=Role.ADMIN)
        )
        await session.commit()


async def _user(client_factory: Any, mail: Any, name: str) -> ApiClient:
    client = client_factory()
    await register(client, f"{name}_{uuid.uuid4().hex[:6]}")
    await verify_email(client, mail)
    return client


async def add_trustline(client: ApiClient, asset_id: str, wallet: str) -> dict[str, Any]:
    prepared = await client.post(f"/assets/{asset_id}/trustline/prepare", {"wallet_address": wallet})
    assert prepared["operation"]["status"] == "SIGNATURE_REQUIRED"
    signed = sign_xdr(prepared["unsigned_xdr"], wallet)
    return await client.post(
        f"/assets/operations/{prepared['operation']['id']}/submit", {"signed_xdr": signed}
    )


async def test_registry_lists_xlm_and_usdc(client_factory: Any) -> None:
    assets = await client_factory().get("/assets")
    by_code = {a["asset"]["code"]: a for a in assets}
    assert set(by_code) == {"XLM", "USDC"}
    usdc = by_code["USDC"]
    assert usdc["asset"]["identifier"] == TESTNET_USDC
    assert usdc["asset"]["contract_id"] == USDC_SAC == sac_contract_id(TESTNET_USDC, get_network().passphrase)
    assert usdc["asset"]["type"] == "credit_alphanum4" and usdc["asset"]["decimals"] == 7
    assert usdc["requires_trustline"] is True and usdc["faucet_url"] == "https://faucet.circle.com"
    assert by_code["XLM"]["requires_trustline"] is False
    assert by_code["XLM"]["asset"]["contract_id"] == get_network().native_asset_contract_id


async def test_bounty_creation_accepts_only_enabled_assets(client_factory: Any, outbox_mail: Any) -> None:
    owner = await _user(client_factory, outbox_mail, "asset_owner")
    xlm = await owner.post("/bounties", bounty_payload(), expected=201)
    assert xlm["reward_asset"]["code"] == "XLM" and xlm["reward_asset"]["identifier"] == "native"
    usdc = await owner.post("/bounties", bounty_payload(reward_asset="USDC"), expected=201)
    assert usdc["reward_asset"]["identifier"] == TESTNET_USDC
    full = await owner.post("/bounties", bounty_payload(reward_asset=TESTNET_USDC), expected=201)
    assert full["reward_asset"]["code"] == "USDC"
    bad = await owner.request("POST", "/bounties", json=bounty_payload(reward_asset="FOO"))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "asset_not_supported"

    # A draft may switch its asset; the marketplace filters per asset.
    switched = await owner.patch(f"/bounties/{xlm['id']}", {"reward_asset": "USDC"})
    assert switched["reward_asset"]["code"] == "USDC"
    await owner.patch(f"/bounties/{switched['id']}", {"reward_asset": "native"})
    for b in (xlm, usdc):
        await owner.post(f"/bounties/{b['id']}/publish")
    anon = client_factory()
    only_usdc = await anon.get("/bounties", params={"asset": TESTNET_USDC})
    assert [b["id"] for b in only_usdc["items"]] == [usdc["id"]]
    assert only_usdc["items"][0]["reward_asset"]["code"] == "USDC"
    only_xlm = await anon.get("/bounties", params={"asset": "XLM"})
    assert [b["id"] for b in only_xlm["items"]] == [xlm["id"]]
    bad_filter = await anon.request("GET", "/bounties", params={"asset": "nope:bad"})
    assert bad_filter.status_code == 422


async def test_usdc_bounty_funding_trustlines_and_payout(
    client_factory: Any, outbox_mail: Any, fake_ledger: FakeLedger, chain: FakeStellarChain
) -> None:
    requester = await _user(client_factory, outbox_mail, "usdc_req")
    req_wallet = await own_wallet(requester)
    fake_ledger.add_account(req_wallet, xlm="50")  # no USDC trustline yet
    bounty = await requester.post(
        "/bounties", bounty_payload(reward_asset="USDC", reward_amount="20"), expected=201
    )
    bid = bounty["id"]
    await requester.post(f"/bounties/{bid}/publish")
    usdc_id = next(a["id"] for a in await requester.get("/assets") if a["asset"]["code"] == "USDC")

    readiness = await requester.get(
        f"/bounties/{bid}/funding/readiness", params={"wallet_address": req_wallet}
    )
    assert readiness["trustline"] == "MISSING" and readiness["ready"] is False
    assert readiness["required"] == "20.0000000" and "USDC trustline" in readiness["message"]
    blocked = await requester.request(
        "POST", f"/bounties/{bid}/funding/prepare", json={"wallet_address": req_wallet}
    )
    assert blocked.status_code == 422 and blocked.json()["error"]["code"] == "trustline_missing"

    # Add the trustline through the wallet-signed flow; it is CONFIRMED only once Horizon shows it.
    op = await add_trustline(requester, usdc_id, req_wallet)
    assert op["status"] == "CONFIRMED" and op["explorer_url"].endswith(op["transaction_hash"])
    again = await requester.request(
        "POST", f"/assets/{usdc_id}/trustline/prepare", json={"wallet_address": req_wallet}
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "trustline_exists"

    readiness = await requester.get(
        f"/bounties/{bid}/funding/readiness", params={"wallet_address": req_wallet}
    )
    assert readiness["trustline"] == "ACTIVE" and readiness["available"] == "0.0000000"
    short = await requester.request(
        "POST", f"/bounties/{bid}/funding/prepare", json={"wallet_address": req_wallet}
    )
    assert short.status_code == 422 and short.json()["error"]["code"] == "insufficient_balance"
    assert "0 USDC available" in short.json()["error"]["message"]

    fake_ledger.add_account(req_wallet, xlm="50", assets={TESTNET_USDC: "25"})
    funded_tx = await chain_action(
        requester, f"/bounties/{bid}/funding/prepare", {"wallet_address": req_wallet}
    )
    assert funded_tx["asset"]["code"] == "USDC" and funded_tx["amount"] == "20.0000000"
    detail = await requester.get(f"/bounties/{bid}")
    assert detail["status"] == "FUNDED" and detail["escrow"]["asset"]["identifier"] == TESTNET_USDC
    escrow_key = f"escrow:{bytes.fromhex(detail['escrow']['onchain_bounty_id']).hex()}"
    assert chain.storage[escrow_key]["token"] == USDC_SAC  # the escrow holds USDC through its SAC

    contributor = await _user(client_factory, outbox_mail, "usdc_contrib")
    contrib_wallet = await own_wallet(contributor)
    fake_ledger.add_account(contrib_wallet, xlm="20")
    application = await contributor.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "I have shipped several USDC payout integrations before."},
        expected=201,
    )
    lines = await requester.get(f"/bounties/{bid}/trustlines")
    assert lines["requires_trustline"] is True
    assert lines["applicants"] == [
        {"contributor_id": contributor.me["id"], "address": contrib_wallet, "state": "MISSING"}  # type: ignore[index]
    ]
    no_line = await requester.request("POST", f"/applications/{application['id']}/accept", json={})
    error = no_line.json()["error"]
    assert no_line.status_code == 422 and error["code"] == "trustline_missing"
    assert error["message"] == (
        f"{contributor.me['display_name']}'s wallet can't receive USDC yet. They need to add a USDC trustline."  # type: ignore[index]
    )
    await drain_events()
    notes = (await contributor.get("/notifications"))["items"]
    assert any(n["title"] == "Add a USDC trustline" and n["link"] == "/app/profile#assets" for n in notes)

    wallets = await contributor.get("/assets/wallets")
    assert wallets[0]["address"] == contrib_wallet
    assert {t["asset"]["code"]: t["state"] for t in wallets[0]["trustlines"]} == {"USDC": "MISSING"}
    await add_trustline(contributor, usdc_id, contrib_wallet)
    wallets = await contributor.get("/assets/wallets")
    assert wallets[0]["trustlines"][0]["state"] == "ACTIVE"

    accepted = await requester.post(f"/applications/{application['id']}/accept", {})
    submission = await contributor.post(
        f"/bounties/{bid}/submissions",
        {
            "description": "Integrated the USDC payout flow with tests.",
            "evidence_url": "https://github.com/x/pr/2",
        },
        expected=201,
    )
    await requester.post(f"/submissions/{submission['id']}/approve", {"feedback": "Great"})
    assert accepted["assignment_id"]

    # The trustline disappears before payout: the release is refused before anything is signed.
    fake_ledger.add_account(contrib_wallet, xlm="20")
    from app.modules.assets.checks import invalidate_trustline

    await invalidate_trustline(contrib_wallet, TESTNET_USDC)
    refused = await requester.request(
        "POST",
        f"/bounties/{bid}/payouts/prepare",
        json={"wallet_address": req_wallet, "submission_id": submission["id"]},
    )
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "trustline_missing"
    assert refused.json()["error"]["details"]["stage"] == "payout"

    fake_ledger.add_account(contrib_wallet, xlm="20", assets={TESTNET_USDC: "0"})
    await invalidate_trustline(contrib_wallet, TESTNET_USDC)
    payout = await chain_action(
        requester,
        f"/bounties/{bid}/payouts/prepare",
        {"wallet_address": req_wallet, "submission_id": submission["id"]},
    )
    assert payout["destination_address"] == contrib_wallet and payout["asset"]["code"] == "USDC"
    paid = await contributor.get(f"/submissions/{submission['id']}")
    assert paid["payment"]["payment_status"] == "CONFIRMED" and paid["payment"]["asset"]["code"] == "USDC"

    # Per-asset totals: USDC is never added to XLM.
    public = await client_factory().get("/analytics/public")
    assert public["verified_payout_volume"] == "0.0000000"
    assert [(v["asset"]["code"], v["amount"]) for v in public["payout_volume_by_asset"]] == [
        ("USDC", "20.0000000")
    ]
    stats = await contributor.get(f"/users/{contributor.me['username']}/stats")  # type: ignore[index]
    assert stats["total_rewards_received"] == "0.0000000"
    assert [(v["asset"]["code"], v["amount"]) for v in stats["rewards_received_by_asset"]] == [
        ("USDC", "20.0000000")
    ]
    mine = await requester.get("/analytics/me")
    assert [(v["asset"]["code"], v["amount"]) for v in mine["requester"]["paid_by_asset"]] == [
        ("USDC", "20.0000000")
    ]
    assert mine["requester"]["spending_by_asset"][0]["asset"]["code"] == "USDC"
    assert mine["requester"]["spending_by_asset"][0]["total"] == "20.0000000"
    earned = await contributor.get("/analytics/me")
    assert earned["contributor"]["earned_by_asset"][0]["amount"] == "20.0000000"

    await drain_events()
    confirmed = [
        n for n in (await contributor.get("/notifications"))["items"] if n["title"] == "Payment received"
    ]
    assert confirmed and "20 USDC" in confirmed[0]["message"]


async def test_trustline_checks_fail_open_when_horizon_is_down(
    client_factory: Any, outbox_mail: Any, fake_ledger: FakeLedger
) -> None:
    requester = await _user(client_factory, outbox_mail, "down_req")
    wallet = await own_wallet(requester)
    bounty = await requester.post("/bounties", bounty_payload(reward_asset="USDC"), expected=201)
    await requester.post(f"/bounties/{bounty['id']}/publish")
    fake_ledger.horizon_down = True
    readiness = await requester.get(
        f"/bounties/{bounty['id']}/funding/readiness", params={"wallet_address": wallet}
    )
    assert (
        readiness["trustline"] == "UNKNOWN" and readiness["ready"] is False and readiness["message"] is None
    )
    # Nothing is blocked on an unknown state: the simulation (here, the fake chain) still decides.
    prepared = await requester.post(f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    assert prepared["summary"]["asset"]["code"] == "USDC"
    assert "USDC" in prepared["summary"]["description"]


async def test_admin_adds_deploys_and_toggles_an_asset(
    client_factory: Any, outbox_mail: Any, fake_ledger: FakeLedger
) -> None:
    admin = await _user(client_factory, outbox_mail, "asset_admin")
    user = await _user(client_factory, outbox_mail, "asset_user")
    denied = await user.request("GET", "/admin/assets")
    assert denied.status_code == 403
    await make_admin(admin)
    admin_wallet = await own_wallet(admin)

    listed = await admin.get("/admin/assets")
    assert {a["asset"]["code"] for a in listed} == {"XLM", "USDC"}
    assert all(a["is_enabled"] and a["contract_status"] == "DEPLOYED" for a in listed)

    issuer = Keypair.random().public_key
    fake_ledger.add_account(issuer, xlm="10")
    fake_ledger.known_assets.add(f"BFT:{issuer}")  # a classic asset whose SAC nobody has deployed yet
    created = await admin.post(
        "/admin/assets", {"code": "BFT", "issuer": issuer, "name": "BountyFlow Test"}, expected=201
    )
    assert created["contract_status"] == "NOT_DEPLOYED" and created["is_enabled"] is False
    assert created["asset"]["contract_id"] == sac_contract_id(f"BFT:{issuer}", get_network().passphrase)
    enable_early = await admin.request("PATCH", f"/admin/assets/{created['id']}", json={"is_enabled": True})
    assert enable_early.status_code == 409
    duplicate = await admin.request("POST", "/admin/assets", json={"code": "BFT", "issuer": issuer})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "asset_exists"
    fake_ledger.permissive = False
    no_issuer = await admin.request(
        "POST", "/admin/assets", json={"code": "ZZZ", "issuer": Keypair.random().public_key}
    )
    assert no_issuer.status_code == 422 and no_issuer.json()["error"]["code"] == "asset_issuer_missing"
    fake_ledger.permissive = True
    not_sac = await admin.request("POST", "/admin/assets", json={"contract_id": "C" + "A" * 55})
    assert not_sac.status_code == 422

    # Deploy the SAC with the admin's wallet: CONFIRMED only once the contract exists on the network.
    prepared = await admin.post(
        f"/admin/assets/{created['id']}/deploy/prepare", {"wallet_address": admin_wallet}
    )
    signed = sign_xdr(prepared["unsigned_xdr"], admin_wallet)
    op = await admin.post(f"/assets/operations/{prepared['operation']['id']}/submit", {"signed_xdr": signed})
    assert op["status"] == "CONFIRMED" and op["kind"] == "DEPLOY_CONTRACT"
    refreshed = next(a for a in await admin.get("/admin/assets") if a["id"] == created["id"])
    assert refreshed["contract_status"] == "DEPLOYED" and refreshed["symbol"] == "BFT"

    enabled = await admin.patch(f"/admin/assets/{created['id']}", {"is_enabled": True})
    assert enabled["is_enabled"] is True
    assert "BFT" in {a["asset"]["code"] for a in await user.get("/assets")}
    by_contract = await admin.request(
        "POST", "/admin/assets", json={"contract_id": created["asset"]["contract_id"]}
    )
    assert by_contract.status_code == 409

    disabled = await admin.patch(f"/admin/assets/{created['id']}", {"is_enabled": False})
    assert disabled["is_enabled"] is False
    assert "BFT" not in {a["asset"]["code"] for a in await user.get("/assets")}
    refused = await user.request("POST", "/bounties", json=bounty_payload(reward_asset=f"BFT:{issuer}"))
    assert refused.status_code == 422


async def test_a_batch_payout_names_the_leg_that_cannot_receive(
    db_session: Any, chain: FakeStellarChain, fake_ledger: FakeLedger
) -> None:
    """``batch_release`` pays every leg atomically, so a single missing trustline must be caught before the
    requester signs, naming the wallet to drop from the batch."""
    from app.modules.assets.checks import ensure_batch_can_receive
    from tests.integration.factories import make_assignment, make_bounty, make_user

    requester = await make_user(db_session)
    ready = await make_user(db_session, display_name="Mira Kovac")
    blocked = await make_user(db_session, display_name="Kai Tanaka")
    bounty = await make_bounty(db_session, requester, reward_asset_identifier=TESTNET_USDC)
    ready_assignment = await make_assignment(db_session, bounty, ready)
    blocked_assignment = await make_assignment(db_session, bounty, blocked)
    await db_session.commit()

    ready_wallet, blocked_wallet = Keypair.random().public_key, Keypair.random().public_key
    fake_ledger.add_account(ready_wallet, xlm="20", assets={TESTNET_USDC: "0"})
    fake_ledger.add_account(blocked_wallet, xlm="20")  # funded, but no USDC trustline
    legs = [
        {"assignment_id": str(ready_assignment.id), "contributor": ready_wallet},
        {"assignment_id": str(blocked_assignment.id), "contributor": blocked_wallet},
    ]

    with pytest.raises(ValidationFailed) as excinfo:
        await ensure_batch_can_receive(db_session, bounty, TESTNET_USDC, legs, actor_id=requester.id)
    assert excinfo.value.code == "trustline_missing"
    assert "Kai Tanaka's wallet can't receive USDC yet" in excinfo.value.message
    assert "batch pays every contributor in one transaction" in excinfo.value.message
    assert excinfo.value.details["address"] == blocked_wallet

    # Once that wallet has its trustline, the whole batch is allowed. The trustline state is cached briefly;
    # adding one through BountyFlow clears it, and a trustline added in another wallet app is simulated here.
    from app.modules.assets.checks import invalidate_trustline

    fake_ledger.add_account(blocked_wallet, xlm="20", assets={TESTNET_USDC: "0"})
    await invalidate_trustline(blocked_wallet, TESTNET_USDC)
    await ensure_batch_can_receive(db_session, bounty, TESTNET_USDC, legs, actor_id=requester.id)
