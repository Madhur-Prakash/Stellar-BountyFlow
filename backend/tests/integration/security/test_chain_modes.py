"""Blockchain trust boundaries in the real-network configuration (Testnet, `FakeStellarChain` test double).

* Only real signatures are accepted. The literal "SIMULATED" marker of the removed development chain, or any other
  non-signature, is rejected as a wallet proof and as a transaction signature (SEC-08).
* A transaction row prepared for another network can never be submitted on this one (SEC-08).
* Submitted envelopes must be exactly the prepared transaction, from the expected source, signed by it for this network.
* A user cannot submit someone else's prepared transaction.
* Production configuration refuses insecure settings, and the simulated chain mode can't be configured at all.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from stellar_sdk import Account, Keypair, TransactionBuilder, TransactionEnvelope

from app.blockchain.verification import EnvelopeMismatch, verify_signed_envelope
from app.core.config import MAINNET_PASSPHRASE, TESTNET_PASSPHRASE, Settings
from app.core.security import utcnow
from app.modules.payments.models import BlockchainTransaction, TxStatus, TxType
from tests.integration.api.conftest import API_ENV, KEYRING, ApiClient, sign_xdr
from tests.integration.security.helpers import new_requester, new_user, published
from tests.support.fake_chain import FakeStellarChain

NON_SIGNATURES = ("SIMULATED", "simulated", "not-xdr")


def _unsigned_tx(source: Keypair) -> Any:
    return (
        TransactionBuilder(Account(source.public_key, 41), TESTNET_PASSPHRASE, base_fee=100)
        .append_bump_sequence_op(42)
        .set_timeout(300)
        .build()
    )


async def test_non_signatures_are_rejected_as_wallet_proofs(client_factory: Any) -> None:
    """SEC-08: a wallet is linked only on a real SEP-10 signature. The development marker (and any other
    non-signature, including the unsigned challenge itself) is refused."""
    client = await new_user(client_factory, "marker")
    address = Keypair.random().public_key
    for bad in (*NON_SIGNATURES, None):
        challenge = await client.post("/wallets/challenge", {"public_address": address})
        assert challenge["network_passphrase"] == TESTNET_PASSPHRASE
        proof = bad or challenge["challenge_xdr"]  # None: submit the challenge unsigned
        response = await client.request(
            "POST", "/wallets/verify", json={"public_address": address, "signed_challenge_xdr": proof}
        )
        assert response.status_code == 422, (bad, response.text)
    assert await client.get("/wallets") == []


async def test_wallet_challenge_is_bound_to_user_and_address(client_factory: Any) -> None:
    """A challenge issued to Alice cannot be redeemed by Bob (even with a valid signature), and a wallet proven
    by one account can never be linked to a second account."""
    alice, bob = await new_user(client_factory, "alice"), await new_user(client_factory, "bob")
    kp = Keypair.random()
    challenge = await alice.post("/wallets/challenge", {"public_address": kp.public_key})
    envelope = TransactionEnvelope.from_xdr(challenge["challenge_xdr"], TESTNET_PASSPHRASE)
    envelope.sign(kp)
    stolen = await bob.request(
        "POST",
        "/wallets/verify",
        json={"public_address": kp.public_key, "signed_challenge_xdr": envelope.to_xdr()},
    )
    assert stolen.status_code == 422  # no challenge was issued to Bob for this address
    linked = await alice.post(
        "/wallets/verify", {"public_address": kp.public_key, "signed_challenge_xdr": envelope.to_xdr()}
    )
    assert linked["verification_status"] == "VERIFIED" and linked["network"] == "testnet"
    replay = await alice.request(
        "POST",
        "/wallets/verify",
        json={"public_address": kp.public_key, "signed_challenge_xdr": envelope.to_xdr()},
    )
    assert replay.status_code == 422  # single use

    # Bob controls the key too (e.g. shared/leaked): he still cannot claim an already-linked wallet.
    challenge = await bob.post("/wallets/challenge", {"public_address": kp.public_key})
    envelope = TransactionEnvelope.from_xdr(challenge["challenge_xdr"], TESTNET_PASSPHRASE)
    envelope.sign(kp)
    dup = await bob.request(
        "POST",
        "/wallets/verify",
        json={"public_address": kp.public_key, "signed_challenge_xdr": envelope.to_xdr()},
    )
    assert dup.status_code == 409


async def test_transaction_prepared_for_another_network_cannot_be_submitted(
    client_factory: Any, db_session: Any, chain: FakeStellarChain
) -> None:
    """SEC-08: a transaction row prepared for another network (e.g. before the deployment switched networks) can
    never be submitted here, not even with a genuine signature, and the network is never contacted."""
    client = await new_user(client_factory, "othernet")
    assert client.me is not None
    wallet = Keypair.random()
    tx = _unsigned_tx(wallet)
    row = BlockchainTransaction(
        id=uuid.uuid4(),
        user_id=uuid.UUID(client.me["id"]),
        transaction_hash=tx.hash_hex(),
        transaction_type=TxType.ESCROW_FUND,
        network="mainnet",
        status=TxStatus.SIGNATURE_REQUIRED,
        source_address=wallet.public_key,
        expires_at=utcnow() + timedelta(minutes=5),
        verification_metadata={},
    )
    db_session.add(row)
    await db_session.commit()
    genuine = TransactionEnvelope.from_xdr(tx.to_xdr(), TESTNET_PASSPHRASE)
    genuine.sign(wallet)
    for signed_xdr in (genuine.to_xdr(), "SIMULATED"):
        response = await client.request(
            "POST", f"/transactions/{row.id}/submit", json={"signed_xdr": signed_xdr}
        )
        assert response.status_code in (409, 422), response.text
    assert chain.submit_calls == 0


async def test_signed_envelope_pipeline_cannot_be_bypassed(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    owner, wallet = await new_requester(client_factory, outbox_mail, "pipeline")
    other = await new_user(client_factory, "intruder")
    bounty = await published(owner)
    prepared = await owner.post(f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    unsigned = prepared["unsigned_xdr"]
    path = f"/transactions/{prepared['transaction']['id']}/submit"

    async def attempt(client: ApiClient, xdr: str) -> Any:
        return await client.request("POST", path, json={"signed_xdr": xdr})

    # Another user can never submit (or even see) my prepared transaction.
    signed_ok = sign_xdr(unsigned, wallet)
    assert (await attempt(other, signed_ok)).status_code == 404
    assert (await other.request("GET", f"/transactions/{prepared['transaction']['id']}")).status_code == 404

    for bad in (*NON_SIGNATURES, unsigned):  # the development marker is not a signature
        r = await attempt(owner, bad)
        assert r.status_code == 422, (bad, r.text)
    wrong_signer = TransactionEnvelope.from_xdr(unsigned, TESTNET_PASSPHRASE)
    wrong_signer.sign(Keypair.random())
    assert (await attempt(owner, wrong_signer.to_xdr())).status_code == 422
    tampered = TransactionEnvelope.from_xdr(unsigned, TESTNET_PASSPHRASE)  # same source, other sequence
    tampered.transaction.sequence += 5
    tampered.sign(KEYRING[wallet])
    assert (await attempt(owner, tampered.to_xdr())).status_code == 422
    other_network = TransactionEnvelope.from_xdr(unsigned, MAINNET_PASSPHRASE)  # signature bound to mainnet
    other_network.sign(KEYRING[wallet])
    assert (await attempt(owner, other_network.to_xdr())).status_code == 422
    assert chain.submit_calls == 0 and chain.submitted == []

    accepted = await owner.post(path, {"signed_xdr": signed_ok})
    assert accepted["status"] == "CONFIRMED"
    assert chain.submitted == [prepared["transaction"]["transaction_hash"]]


def test_verify_signed_envelope_unit() -> None:
    source = Keypair.random()
    tx = _unsigned_tx(source)
    expected = tx.hash_hex()
    signed = TransactionEnvelope.from_xdr(tx.to_xdr(), TESTNET_PASSPHRASE)
    signed.sign(source)
    ok = verify_signed_envelope(
        signed.to_xdr(),
        expected_hash=expected,
        expected_source=source.public_key,
        network_passphrase=TESTNET_PASSPHRASE,
    )
    assert ok.source == source.public_key
    with pytest.raises(EnvelopeMismatch):
        verify_signed_envelope(
            signed.to_xdr(),
            expected_hash=expected,
            expected_source=Keypair.random().public_key,
            network_passphrase=TESTNET_PASSPHRASE,
        )
    with pytest.raises(EnvelopeMismatch):  # a signature is bound to the network passphrase
        verify_signed_envelope(
            signed.to_xdr(),
            expected_hash=expected,
            expected_source=source.public_key,
            network_passphrase=MAINNET_PASSPHRASE,
        )
    with pytest.raises(EnvelopeMismatch):  # the development marker is not an envelope
        verify_signed_envelope(
            "SIMULATED",
            expected_hash=expected,
            expected_source=source.public_key,
            network_passphrase=TESTNET_PASSPHRASE,
        )


# --- Configuration --------------------------------------------------------------------------------------


def _production(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "production",
        "jwt_secret": "k3y-" + uuid.uuid4().hex + uuid.uuid4().hex,
        "cookie_secure": True,
        "blockchain_mode": "testnet",
        "stellar_network": "testnet",
        "stellar_network_passphrase": TESTNET_PASSPHRASE,
        "soroban_contract_id": API_ENV["SOROBAN_CONTRACT_ID"],
        "wallet_challenge_signing_secret": Keypair.random().secret,
        "cors_origins": ["https://bountyflow.example.com"],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_production_configuration_is_validated() -> None:
    assert _production().is_production
    insecure = [
        {"cookie_secure": False},
        {"jwt_secret": "short"},
        {"jwt_secret": "REPLACE-with-a-long-random-secret-dev-only-0000000000"},
        {"wallet_challenge_signing_secret": None},
        {"soroban_contract_id": None},
        {"cors_origins": ["*"]},
    ]
    for override in insecure:
        with pytest.raises(ValidationError):
            _production(**override)


@pytest.mark.parametrize("override", [{"blockchain_mode": "simulated"}, {"stellar_network": "simulated"}])
def test_simulated_chain_mode_cannot_be_configured(override: dict[str, str]) -> None:
    """The simulated development chain was removed: no environment can switch it back on by configuration."""
    for app_env in ("development", "test"):
        baseline = Settings(_env_file=None, app_env=app_env)  # type: ignore[call-arg]
        assert baseline.app_env == app_env
        with pytest.raises(ValidationError):
            Settings(_env_file=None, app_env=app_env, **override)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        _production(**override)


def test_jwt_algorithm_is_pinned_to_hmac() -> None:
    with pytest.raises(ValidationError):
        _production(jwt_algorithm="none")
    with pytest.raises(ValidationError):
        _production(jwt_algorithm="RS256")  # the verifier holds a shared secret, not a public key
