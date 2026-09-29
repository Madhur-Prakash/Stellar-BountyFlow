"""Wallet ownership proofs and passkey deployment checks, without a network.

SEP-10 and SEP-53 are verified offline against real keypairs; the passkey deployment checks parse a real
``CreateContractV2`` carrier built exactly as passkey-kit builds it.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from stellar_sdk import Account, Address, Keypair, TransactionBuilder
from stellar_sdk import xdr as stellar_xdr

from app.blockchain import passkey
from app.blockchain import wallet as wallet_proof
from app.core.config import get_settings
from app.core.exceptions import ValidationFailed

PASSPHRASE = "Test SDF Network ; September 2015"


@pytest.fixture(autouse=True)
def _network(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.blockchain.config import get_network

    monkeypatch.setenv("STELLAR_NETWORK_PASSPHRASE", PASSPHRASE)
    monkeypatch.setenv("BLOCKCHAIN_MODE", "testnet")
    monkeypatch.setenv("STELLAR_NETWORK", "testnet")
    monkeypatch.setenv("PASSKEY_WALLET_WASM_HASH", "aa" * 32)
    get_settings.cache_clear()
    get_network.cache_clear()
    wallet_proof.server_keypair.cache_clear()
    yield
    get_settings.cache_clear()
    get_network.cache_clear()
    wallet_proof.server_keypair.cache_clear()


# --- Addresses ---------------------------------------------------------------------------------


def test_contract_addresses_are_only_accepted_where_they_are_allowed() -> None:
    account = Keypair.random().public_key
    contract = passkey.derive_contract_id(b"credential-id")
    assert wallet_proof.validate_address(account) == account
    assert wallet_proof.validate_address(contract, allow_contract=True) == contract
    with pytest.raises(ValidationFailed):
        wallet_proof.validate_address(contract)
    with pytest.raises(ValidationFailed):
        wallet_proof.validate_address("not-an-address", allow_contract=True)


def test_the_proof_method_follows_the_address_kind() -> None:
    assert wallet_proof.default_method(Keypair.random().public_key) == "sep10"
    assert wallet_proof.default_method(passkey.derive_contract_id(b"k")) == "sep45"


# --- SEP-53 signed messages ---------------------------------------------------------------------


def test_a_signed_message_proves_the_account_and_nothing_else() -> None:
    keypair = Keypair.random()
    other = Keypair.random()
    expires = datetime.now(UTC) + timedelta(minutes=5)
    message = wallet_proof.challenge_message(keypair.public_key, "nonce-value", expires)
    record = {"method": "sep53", "message": message}

    wallet_proof._verify_sep53(record, keypair.public_key, wallet_proof.sep53_signature(keypair, message))
    # Hex and base64url encodings of the same signature are both accepted.
    wallet_proof._verify_sep53(record, keypair.public_key, keypair.sign_message(message).hex())

    with pytest.raises(ValidationFailed):  # another key's signature
        wallet_proof._verify_sep53(record, keypair.public_key, wallet_proof.sep53_signature(other, message))
    with pytest.raises(ValidationFailed):  # a signature of another message
        wallet_proof._verify_sep53(
            record, keypair.public_key, wallet_proof.sep53_signature(keypair, message + "!")
        )
    with pytest.raises(ValidationFailed):  # not a signature at all
        wallet_proof._verify_sep53(record, keypair.public_key, base64.b64encode(b"short").decode())


def test_the_message_names_the_address_network_and_nonce() -> None:
    address = Keypair.random().public_key
    message = wallet_proof.challenge_message(address, "abc123", datetime.now(UTC))
    assert address in message
    assert "abc123" in message
    assert "testnet" in message


# --- SEP-10 challenge transactions ----------------------------------------------------------------


def test_a_challenge_signed_by_another_key_is_refused() -> None:
    from stellar_sdk import TransactionEnvelope
    from stellar_sdk.sep.stellar_web_authentication import build_challenge_transaction

    settings = get_settings()
    client = Keypair.random()
    xdr = build_challenge_transaction(
        server_secret=wallet_proof.server_keypair().secret,
        client_account_id=client.public_key,
        home_domain=settings.wallet_challenge_home_domain,
        web_auth_domain=wallet_proof.WEB_AUTH_DOMAIN,
        network_passphrase=PASSPHRASE,
        timeout=300,
    )
    envelope = TransactionEnvelope.from_xdr(xdr, PASSPHRASE)
    record = {"method": "sep10", "hash": envelope.hash_hex(), "xdr": xdr}

    envelope.sign(client)
    wallet_proof._verify_sep10(record, client.public_key, envelope.to_xdr())

    impostor = TransactionEnvelope.from_xdr(xdr, PASSPHRASE)
    impostor.sign(Keypair.random())
    with pytest.raises(ValidationFailed):
        wallet_proof._verify_sep10(record, client.public_key, impostor.to_xdr())


def test_a_challenge_for_another_address_never_matches_the_issued_hash() -> None:
    from stellar_sdk import TransactionEnvelope
    from stellar_sdk.sep.stellar_web_authentication import build_challenge_transaction

    settings = get_settings()
    mine, theirs = Keypair.random(), Keypair.random()
    issued = build_challenge_transaction(
        server_secret=wallet_proof.server_keypair().secret,
        client_account_id=mine.public_key,
        home_domain=settings.wallet_challenge_home_domain,
        web_auth_domain=wallet_proof.WEB_AUTH_DOMAIN,
        network_passphrase=PASSPHRASE,
        timeout=300,
    )
    other = build_challenge_transaction(
        server_secret=wallet_proof.server_keypair().secret,
        client_account_id=theirs.public_key,
        home_domain=settings.wallet_challenge_home_domain,
        web_auth_domain=wallet_proof.WEB_AUTH_DOMAIN,
        network_passphrase=PASSPHRASE,
        timeout=300,
    )
    record = {"method": "sep10", "hash": TransactionEnvelope.from_xdr(issued, PASSPHRASE).hash_hex()}
    signed_other = TransactionEnvelope.from_xdr(other, PASSPHRASE)
    signed_other.sign(theirs)
    with pytest.raises(ValidationFailed):
        wallet_proof._verify_sep10(record, mine.public_key, signed_other.to_xdr())


# --- SEP-45 challenge merging ----------------------------------------------------------------------


def _address_entry(
    address: str, nonce: int, signature: stellar_xdr.SCVal, *, args: list[stellar_xdr.SCVal] | None = None
) -> stellar_xdr.SorobanAuthorizationEntry:
    return stellar_xdr.SorobanAuthorizationEntry(
        credentials=stellar_xdr.SorobanCredentials(
            type=stellar_xdr.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS,
            address=stellar_xdr.SorobanAddressCredentials(
                address=Address(address).to_xdr_sc_address(),
                nonce=stellar_xdr.Int64(nonce),
                signature_expiration_ledger=stellar_xdr.Uint32(100),
                signature=signature,
            ),
        ),
        root_invocation=stellar_xdr.SorobanAuthorizedInvocation(
            function=stellar_xdr.SorobanAuthorizedFunction(
                type=stellar_xdr.SorobanAuthorizedFunctionType.SOROBAN_AUTHORIZED_FUNCTION_TYPE_CONTRACT_FN,
                contract_fn=stellar_xdr.InvokeContractArgs(
                    contract_address=Address(passkey.derive_contract_id(b"web-auth")).to_xdr_sc_address(),
                    function_name=stellar_xdr.SCSymbol(b"web_auth_verify"),
                    args=args or [],
                ),
            ),
            sub_invocations=[],
        ),
    )


def _entries(*entries: stellar_xdr.SorobanAuthorizationEntry) -> str:
    return stellar_xdr.SorobanAuthorizationEntries(list(entries)).to_xdr()


SIGNED = stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_BYTES, bytes=stellar_xdr.SCBytes(b"signature"))
UNSIGNED = stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_VOID)


def test_only_the_wallets_own_signed_entry_is_taken_from_the_client() -> None:
    server = Keypair.random().public_key
    contract = passkey.derive_contract_id(b"wallet")
    issued = _entries(_address_entry(server, 1, SIGNED), _address_entry(contract, 2, UNSIGNED))
    answered = _entries(_address_entry(server, 1, SIGNED), _address_entry(contract, 2, SIGNED))

    merged = wallet_proof._merge_signed_entries(issued, answered, contract)
    parsed = stellar_xdr.SorobanAuthorizationEntries.from_xdr(merged).soroban_authorization_entries
    assert len(parsed) == 2
    assert parsed[1].credentials.address is not None
    assert parsed[1].credentials.address.signature == SIGNED
    # The server's own entry is the issued one, never whatever the client returned for it.
    assert parsed[0].to_xdr() == _address_entry(server, 1, SIGNED).to_xdr()


def test_an_unsigned_or_foreign_challenge_answer_is_refused() -> None:
    server = Keypair.random().public_key
    contract = passkey.derive_contract_id(b"wallet")
    issued = _entries(_address_entry(server, 1, SIGNED), _address_entry(contract, 2, UNSIGNED))

    # Not signed at all.
    with pytest.raises(ValidationFailed):
        wallet_proof._merge_signed_entries(issued, issued, contract)

    # Another wallet's entry: nothing for this address.
    other = _entries(_address_entry(passkey.derive_contract_id(b"other"), 2, SIGNED))
    with pytest.raises(ValidationFailed):
        wallet_proof._merge_signed_entries(issued, other, contract)

    # A signature over a different call than the one that was issued.
    from stellar_sdk import scval

    tampered = _entries(_address_entry(contract, 2, SIGNED, args=[scval.to_string("other-challenge")]))
    with pytest.raises(ValidationFailed):
        wallet_proof._merge_signed_entries(issued, tampered, contract)


# --- Passkey deployments -----------------------------------------------------------------------------


def _signer(key_id: bytes, public_key: bytes) -> stellar_xdr.SCVal:
    from stellar_sdk import scval

    return scval.to_vec(
        [
            scval.to_symbol("Secp256r1"),
            scval.to_bytes(key_id),
            scval.to_bytes(public_key),
            scval.to_void(),
            scval.to_void(),
            scval.to_vec([scval.to_symbol("Persistent")]),
        ]
    )


def _deploy_carrier(
    key_id: bytes, public_key: bytes, *, wasm: bytes | None = None, deployer: str | None = None
) -> str:
    """A CreateContractV2 carrier shaped exactly like the one passkey-kit's `createWallet` returns."""
    from stellar_sdk.operation import InvokeHostFunction

    deployer_address = deployer or passkey.DEPLOYER
    create = stellar_xdr.CreateContractArgsV2(
        contract_id_preimage=stellar_xdr.ContractIDPreimage(
            type=stellar_xdr.ContractIDPreimageType.CONTRACT_ID_PREIMAGE_FROM_ADDRESS,
            from_address=stellar_xdr.ContractIDPreimageFromAddress(
                address=Address(deployer_address).to_xdr_sc_address(),
                salt=stellar_xdr.Uint256(hashlib.sha256(key_id).digest()),
            ),
        ),
        executable=stellar_xdr.ContractExecutable(
            type=stellar_xdr.ContractExecutableType.CONTRACT_EXECUTABLE_WASM,
            wasm_hash=stellar_xdr.Hash(wasm or bytes.fromhex("aa" * 32)),
        ),
        constructor_args=[_signer(key_id, public_key), stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_VOID)],
    )
    host_function = stellar_xdr.HostFunction(
        type=stellar_xdr.HostFunctionType.HOST_FUNCTION_TYPE_CREATE_CONTRACT_V2, create_contract_v2=create
    )
    entry = stellar_xdr.SorobanAuthorizationEntry(
        credentials=stellar_xdr.SorobanCredentials(
            type=stellar_xdr.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS,
            address=stellar_xdr.SorobanAddressCredentials(
                address=Address(deployer_address).to_xdr_sc_address(),
                nonce=stellar_xdr.Int64(7),
                signature_expiration_ledger=stellar_xdr.Uint32(1000),
                signature=SIGNED,
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
        TransactionBuilder(Account(Keypair.random().public_key, 1), PASSPHRASE, base_fee=100)
        .append_operation(InvokeHostFunction(host_function=host_function, auth=[entry]))
        .set_timeout(60)
        .build()
    )
    return tx.to_xdr()


def _credential() -> tuple[bytes, str, bytes]:
    key_id = b"passkey-credential-id"
    key_id_b64 = base64.urlsafe_b64encode(key_id).rstrip(b"=").decode()
    public_key = bytes([0x04]) + bytes(range(64))
    return key_id, key_id_b64, public_key


def test_a_deployment_is_accepted_only_for_the_registered_passkey() -> None:
    key_id, key_id_b64, public_key = _credential()
    deployment = passkey.check_deployment(_deploy_carrier(key_id, public_key), key_id_b64, public_key.hex())
    assert deployment.contract_id == passkey.derive_contract_id(key_id)
    assert deployment.key_id == key_id_b64
    assert deployment.public_key == public_key.hex()
    assert deployment.wasm_hash == "aa" * 32
    assert len(deployment.auth) == 1


def test_a_deployment_that_installs_another_passkey_is_refused() -> None:
    key_id, key_id_b64, public_key = _credential()
    other_key = bytes([0x04]) + bytes(range(64, 128))
    with pytest.raises(ValidationFailed):
        passkey.check_deployment(_deploy_carrier(key_id, other_key), key_id_b64, public_key.hex())


def test_a_deployment_of_unexpected_code_or_by_another_deployer_is_refused() -> None:
    key_id, key_id_b64, public_key = _credential()
    with pytest.raises(ValidationFailed):  # not the smart-wallet wasm BountyFlow configured
        passkey.check_deployment(
            _deploy_carrier(key_id, public_key, wasm=bytes.fromhex("bb" * 32)), key_id_b64, public_key.hex()
        )
    with pytest.raises(ValidationFailed):  # a deployer whose derivation BountyFlow cannot reproduce
        passkey.check_deployment(
            _deploy_carrier(key_id, public_key, deployer=Keypair.random().public_key),
            key_id_b64,
            public_key.hex(),
        )


def test_the_wallet_address_derives_from_the_credential_id_alone() -> None:
    first = passkey.derive_contract_id(b"credential-a")
    again = passkey.derive_contract_id(b"credential-a")
    other = passkey.derive_contract_id(b"credential-b")
    assert first == again != other
    assert first.startswith("C")
