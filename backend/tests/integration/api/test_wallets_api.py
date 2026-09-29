"""Wallet linking, fee sponsorship and passkey smart wallets, against the API and the chain test double.

The double builds real XDR and runs the real signature verification, so every proof and every sponsorship
decision here is the production code path with the network replaced.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from sqlalchemy import select
from stellar_sdk import Account, Address, Keypair, TransactionBuilder
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.operation import InvokeHostFunction

from app.blockchain import passkey
from app.blockchain.config import get_network
from app.core.config import get_settings
from app.modules.wallets.models import (
    PasskeyWallet,
    PasskeyWalletStatus,
    SponsoredTransaction,
    SponsorshipKind,
    SponsorshipStatus,
)
from tests.integration.api.conftest import (
    KEYRING,
    SPONSOR,
    ApiClient,
    chain_action,
    link_wallet,
    register,
    sign_xdr,
)
from tests.integration.security.helpers import assigned_contributor, funded, new_requester
from tests.support.fake_chain import FakeStellarChain

pytestmark = pytest.mark.integration


# --- Linking ------------------------------------------------------------------------------------


async def test_a_wallet_records_which_app_and_proof_verified_it(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    keypair = Keypair.random()
    KEYRING[keypair.public_key] = keypair

    challenge = await client.post("/wallets/challenge", {"public_address": keypair.public_key})
    assert challenge["method"] == "sep10"
    wallet = await client.post(
        "/wallets/verify",
        {
            "public_address": keypair.public_key,
            "signed_challenge_xdr": sign_xdr(challenge["challenge_xdr"], keypair.public_key),
            "wallet_app": "xbull",
        },
    )
    assert wallet["wallet_app"] == "xbull"
    assert wallet["proof_method"] == "sep10"
    assert wallet["kind"] == "account"


async def test_a_signed_message_links_a_wallet(client_factory: Any) -> None:
    """SEP-53, for wallets that sign messages rather than transactions (e.g. LOBSTR)."""
    client = client_factory()
    await register(client)
    keypair = Keypair.random()

    challenge = await client.post(
        "/wallets/challenge", {"public_address": keypair.public_key, "method": "sep53"}
    )
    assert challenge["method"] == "sep53" and challenge["challenge_xdr"] is None
    assert keypair.public_key in challenge["message"]

    wallet = await client.post(
        "/wallets/verify",
        {
            "public_address": keypair.public_key,
            "signed_message": base64.b64encode(keypair.sign_message(challenge["message"])).decode(),
            "wallet_app": "lobstr",
        },
    )
    assert wallet["proof_method"] == "sep53" and wallet["wallet_app"] == "lobstr"


async def test_a_message_signed_by_another_key_does_not_link_the_wallet(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    keypair, impostor = Keypair.random(), Keypair.random()
    challenge = await client.post(
        "/wallets/challenge", {"public_address": keypair.public_key, "method": "sep53"}
    )
    response = await client.request(
        "POST",
        "/wallets/verify",
        json={
            "public_address": keypair.public_key,
            "signed_message": base64.b64encode(impostor.sign_message(challenge["message"])).decode(),
        },
    )
    assert response.status_code == 422
    assert await client.get("/wallets") == []


async def test_a_challenge_is_single_use_whatever_its_method(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    keypair = Keypair.random()
    challenge = await client.post(
        "/wallets/challenge", {"public_address": keypair.public_key, "method": "sep53"}
    )
    body = {
        "public_address": keypair.public_key,
        "signed_message": base64.b64encode(keypair.sign_message(challenge["message"])).decode(),
    }
    await client.post("/wallets/verify", body)
    replay = await client.request("POST", "/wallets/verify", json=body)
    assert replay.status_code == 422  # the challenge was consumed by the first attempt


async def test_the_payout_wallet_can_be_chosen(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    first = await link_wallet(client)
    second = await link_wallet(client)
    wallets = await client.get("/wallets")
    assert [w["is_primary"] for w in wallets] == [False, False]

    target = next(w for w in wallets if w["public_address"] == first)
    chosen = await client.post(f"/wallets/{target['id']}/primary", {})
    assert chosen["is_primary"] is True
    after = {w["public_address"]: w["is_primary"] for w in await client.get("/wallets")}
    assert after[first] is True and after[second] is False


async def test_another_users_wallet_cannot_be_made_a_payout_wallet(client_factory: Any) -> None:
    owner, other = client_factory(), client_factory()
    await register(owner)
    await register(other)
    await link_wallet(owner)
    wallet_id = (await owner.get("/wallets"))[0]["id"]
    await other.request("POST", f"/wallets/{wallet_id}/primary", json={}, expected=404)


# --- Options -------------------------------------------------------------------------------------


async def test_wallet_options_describe_what_this_server_offers(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    options = await client.get("/wallets/options")
    assert options["sponsorship"]["enabled"] is True
    assert options["sponsorship"]["sponsor_address"] == SPONSOR.public_key
    assert "claim" in options["sponsorship"]["functions"]
    assert options["passkey"]["enabled"] is True
    assert options["passkey"]["wasm_hash"] == get_settings().passkey_wallet_wasm_hash


async def test_everything_switches_off_without_a_sponsor_key(
    client_factory: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STELLAR_SPONSOR_SECRET", raising=False)
    get_settings.cache_clear()
    client = client_factory()
    await register(client)
    options = await client.get("/wallets/options")
    assert options["sponsorship"]["enabled"] is False
    assert options["passkey"]["enabled"] is False
    assert options["passkey"]["unavailable_reason"]
    # Creating a passkey wallet says so instead of failing obscurely.
    response = await client.request(
        "POST",
        "/wallets/passkey",
        json={"key_id": "aaaaaaaa", "public_key": "04" * 32 + "04", "deploy_xdr": "x"},
    )
    assert response.status_code == 503


# --- Fee sponsorship ------------------------------------------------------------------------------


async def _contributor_consent(
    client_factory: Any, outbox_mail: Any
) -> tuple[ApiClient, ApiClient, dict[str, Any], str]:
    """A funded bounty with an on-chain assignment and a cancellation requested: the contributor's
    ``consent_cancel`` is the contributor-side call BountyFlow sponsors."""
    requester, req_wallet = await new_requester(client_factory, outbox_mail, "sponsor_req")
    bounty = await funded(requester, req_wallet, reward_amount="4")
    contributor, con_wallet, accepted = await assigned_contributor(
        client_factory, requester, bounty["id"], "sponsor_con"
    )
    await chain_action(
        requester,
        f"/bounties/{bounty['id']}/chain/prepare",
        {"action": "ASSIGN", "wallet_address": req_wallet, "assignment_id": accepted["assignment_id"]},
    )
    await requester.post(f"/bounties/{bounty['id']}/cancel", {"reason": "Changed my mind about this one."})
    await chain_action(
        requester,
        f"/bounties/{bounty['id']}/chain/prepare",
        {"action": "REQUEST_CANCEL", "wallet_address": req_wallet},
    )
    return requester, contributor, bounty, con_wallet


async def test_a_contributor_call_is_fee_bumped_by_the_sponsor(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain, db_session: Any
) -> None:
    _requester, contributor, bounty, wallet = await _contributor_consent(client_factory, outbox_mail)

    prepared = await contributor.post(
        f"/bounties/{bounty['id']}/chain/prepare",
        {"action": "CONSENT_CANCEL", "wallet_address": wallet},
    )
    assert prepared["summary"]["fee_sponsored"] is True

    tx = await contributor.post(
        f"/transactions/{prepared['transaction']['id']}/submit",
        {"signed_xdr": sign_xdr(prepared["unsigned_xdr"], wallet)},
    )
    tx = await contributor.get(f"/transactions/{tx['id']}")
    assert tx["status"] == "CONFIRMED"
    assert tx["fee_sponsored"] is True
    # The network saw a fee bump paid by the sponsor, carrying the user's unchanged transaction.
    assert chain.fee_bumps[tx["transaction_hash"]] == SPONSOR.public_key

    row = await db_session.scalar(
        select(SponsoredTransaction).where(SponsoredTransaction.inner_hash == tx["transaction_hash"])
    )
    assert row is not None
    assert row.kind == SponsorshipKind.FEE_BUMP
    assert row.status == SponsorshipStatus.CONFIRMED
    assert row.fee_charged_stroops is not None
    assert row.function_name == "consent_cancel"


async def test_the_requesters_own_calls_are_never_sponsored(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    requester, wallet = await new_requester(client_factory, outbox_mail, "unsponsored")
    bounty = await funded(requester, wallet, reward_amount="3")
    await requester.post(f"/bounties/{bounty['id']}/cancel", {"reason": "No longer needed at all."})
    prepared = await requester.post(
        f"/bounties/{bounty['id']}/chain/prepare",
        {"action": "REQUEST_CANCEL", "wallet_address": wallet},
    )
    assert prepared["summary"]["fee_sponsored"] is False
    tx = await requester.post(
        f"/transactions/{prepared['transaction']['id']}/submit",
        {"signed_xdr": sign_xdr(prepared["unsigned_xdr"], wallet)},
    )
    assert chain.fee_bumps.get(tx["transaction_hash"]) is None


async def test_the_daily_cap_stops_sponsoring_and_the_user_still_transacts(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPONSOR_DAILY_TX_LIMIT", "0")
    get_settings.cache_clear()
    _requester, contributor, bounty, wallet = await _contributor_consent(client_factory, outbox_mail)

    prepared = await contributor.post(
        f"/bounties/{bounty['id']}/chain/prepare",
        {"action": "CONSENT_CANCEL", "wallet_address": wallet},
    )
    assert prepared["summary"]["fee_sponsored"] is False
    tx = await contributor.post(
        f"/transactions/{prepared['transaction']['id']}/submit",
        {"signed_xdr": sign_xdr(prepared["unsigned_xdr"], wallet)},
    )
    # Refused sponsorship never blocks the action: the user simply pays their own fee.
    assert (await contributor.get(f"/transactions/{tx['id']}"))["status"] == "CONFIRMED"
    assert chain.fee_bumps.get(tx["transaction_hash"]) is None


async def test_the_admin_overview_reports_the_sponsor(
    client_factory: Any, outbox_mail: Any, db_session: Any
) -> None:
    from app.modules.users.models import Role
    from tests.integration.security.helpers import new_user, set_role

    staff = await new_user(client_factory, "sponsor_staff")
    await set_role(db_session, staff, Role.MODERATOR)
    overview = await staff.get("/admin/sponsorship")
    assert overview["enabled"] is True
    assert overview["sponsor_address"] == SPONSOR.public_key
    assert overview["daily_tx_limit"] == get_settings().sponsor_daily_tx_limit


async def test_the_sponsorship_overview_is_staff_only(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    await client.request("GET", "/admin/sponsorship", expected=403)


# --- Passkey smart wallets --------------------------------------------------------------------------


def _deploy_carrier(key_id: bytes, public_key: bytes) -> str:
    """The CreateContractV2 carrier passkey-kit's ``createWallet`` returns, signed by its shared deployer."""
    from stellar_sdk import scval

    network = get_network()
    signer = scval.to_vec(
        [
            scval.to_symbol("Secp256r1"),
            scval.to_bytes(key_id),
            scval.to_bytes(public_key),
            scval.to_void(),
            scval.to_void(),
            scval.to_vec([scval.to_symbol("Persistent")]),
        ]
    )
    create = stellar_xdr.CreateContractArgsV2(
        contract_id_preimage=stellar_xdr.ContractIDPreimage(
            type=stellar_xdr.ContractIDPreimageType.CONTRACT_ID_PREIMAGE_FROM_ADDRESS,
            from_address=stellar_xdr.ContractIDPreimageFromAddress(
                address=Address(passkey.DEPLOYER).to_xdr_sc_address(),
                salt=stellar_xdr.Uint256(hashlib.sha256(key_id).digest()),
            ),
        ),
        executable=stellar_xdr.ContractExecutable(
            type=stellar_xdr.ContractExecutableType.CONTRACT_EXECUTABLE_WASM,
            wasm_hash=stellar_xdr.Hash(bytes.fromhex(get_settings().passkey_wallet_wasm_hash)),
        ),
        constructor_args=[signer, stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_VOID)],
    )
    host_function = stellar_xdr.HostFunction(
        type=stellar_xdr.HostFunctionType.HOST_FUNCTION_TYPE_CREATE_CONTRACT_V2, create_contract_v2=create
    )
    entry = stellar_xdr.SorobanAuthorizationEntry(
        credentials=stellar_xdr.SorobanCredentials(
            type=stellar_xdr.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS,
            address=stellar_xdr.SorobanAddressCredentials(
                address=Address(passkey.DEPLOYER).to_xdr_sc_address(),
                nonce=stellar_xdr.Int64(11),
                signature_expiration_ledger=stellar_xdr.Uint32(5_000_100),
                signature=stellar_xdr.SCVal(
                    stellar_xdr.SCValType.SCV_BYTES, bytes=stellar_xdr.SCBytes(b"deployer-signature")
                ),
            ),
        ),
        root_invocation=stellar_xdr.SorobanAuthorizedInvocation(
            function=stellar_xdr.SorobanAuthorizedFunction(
                type=(
                    stellar_xdr.SorobanAuthorizedFunctionType.SOROBAN_AUTHORIZED_FUNCTION_TYPE_CREATE_CONTRACT_V2_HOST_FN
                ),
                create_contract_v2_host_fn=create,
            ),
            sub_invocations=[],
        ),
    )
    tx = (
        TransactionBuilder(Account(Keypair.random().public_key, 1), network.passphrase, base_fee=100)
        .append_operation(InvokeHostFunction(host_function=host_function, auth=[entry]))
        .set_timeout(120)
        .build()
    )
    return tx.to_xdr()


def _credential(seed: bytes = b"e2e-credential") -> tuple[str, str, bytes]:
    key_id = hashlib.sha256(seed).digest()[:20]
    key_id_b64 = base64.urlsafe_b64encode(key_id).rstrip(b"=").decode()
    public_key = bytes([0x04]) + hashlib.sha512(seed).digest()
    return key_id_b64, public_key.hex(), key_id


async def test_a_passkey_wallet_is_deployed_by_the_sponsor_and_verified_with_sep45(
    client_factory: Any, db_session: Any
) -> None:
    client = client_factory()
    await register(client)
    key_id_b64, public_key_hex, key_id = _credential()

    wallet = await client.post(
        "/wallets/passkey",
        {
            "key_id": key_id_b64,
            "public_key": public_key_hex,
            "deploy_xdr": _deploy_carrier(key_id, bytes.fromhex(public_key_hex)),
        },
        expected=201,
    )
    assert wallet["contract_id"] == passkey.derive_contract_id(key_id)
    assert wallet["status"] == "ACTIVE"  # the double confirms the deployment immediately
    assert wallet["linked"] is False

    row = await db_session.scalar(
        select(PasskeyWallet).where(PasskeyWallet.contract_id == wallet["contract_id"])
    )
    assert row is not None and row.status == PasskeyWalletStatus.ACTIVE
    sponsored = await db_session.scalar(
        select(SponsoredTransaction).where(SponsoredTransaction.passkey_wallet_id == row.id)
    )
    assert sponsored is not None
    assert sponsored.kind == SponsorshipKind.RELAY and sponsored.purpose == "WALLET_DEPLOY"
    assert sponsored.sponsor_address == SPONSOR.public_key


async def test_a_deployment_that_installs_another_passkey_is_refused(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    key_id_b64, public_key_hex, key_id = _credential(b"mismatch")
    other_key = bytes([0x04]) + hashlib.sha512(b"someone-else").digest()
    response = await client.request(
        "POST",
        "/wallets/passkey",
        json={
            "key_id": key_id_b64,
            "public_key": public_key_hex,
            "deploy_xdr": _deploy_carrier(key_id, other_key),
        },
    )
    assert response.status_code == 422


async def test_another_account_cannot_claim_the_same_passkey_wallet(client_factory: Any) -> None:
    owner, other = client_factory(), client_factory()
    await register(owner)
    await register(other)
    key_id_b64, public_key_hex, key_id = _credential(b"shared")
    body = {
        "key_id": key_id_b64,
        "public_key": public_key_hex,
        "deploy_xdr": _deploy_carrier(key_id, bytes.fromhex(public_key_hex)),
    }
    await owner.post("/wallets/passkey", body, expected=201)
    response = await other.request("POST", "/wallets/passkey", json=body)
    assert response.status_code == 409


async def test_wallet_candidates_only_describe_the_callers_own_wallet(client_factory: Any) -> None:
    owner, other = client_factory(), client_factory()
    await register(owner)
    await register(other)
    key_id_b64, public_key_hex, key_id = _credential(b"candidates")
    await owner.post(
        "/wallets/passkey",
        {
            "key_id": key_id_b64,
            "public_key": public_key_hex,
            "deploy_xdr": _deploy_carrier(key_id, bytes.fromhex(public_key_hex)),
        },
        expected=201,
    )
    mine = await owner.get("/wallets/passkey/candidates", params={"key_id": key_id_b64})
    assert mine["complete"] is True and mine["schema"] == 2
    assert [c["contractId"] for c in mine["candidates"]] == [passkey.derive_contract_id(key_id)]

    theirs = await other.get("/wallets/passkey/candidates", params={"key_id": key_id_b64})
    assert theirs["candidates"] == []


async def test_verified_email_and_permissions_guard_the_passkey_routes(client_factory: Any) -> None:
    anonymous = client_factory()
    anonymous.http.cookies.set("bf_csrf", "anon")
    await anonymous.request("GET", "/wallets/passkey", expected=401)
    await anonymous.request("POST", "/wallets/passkey", json={}, expected=401)
    await anonymous.request("GET", "/wallets/options", expected=401)
