"""Passkey smart wallets: checking a wallet deployment before the sponsor relays it, and verifying it on-chain.

The browser (passkey-kit) registers a WebAuthn passkey and authorizes a ``CreateContractV2`` deployment of the
passkey-kit smart wallet (WASM ``PASSKEY_WALLET_WASM_HASH``) whose constructor makes that passkey the wallet's
only, unlimited signer. passkey-kit derives every wallet address from the credential id with a published,
sign-only deployer key (``sha256("kalepail")``), so a passkey always maps to one address.

The deployer's authorization entry comes from the browser; BountyFlow never trusts it blindly. Before the
sponsor sources and pays for the deployment, ``check_deployment`` requires that the call creates exactly the
expected contract, from the expected code, with the passkey the user registered as its signer, and that the
deployer's authorization covers exactly that deployment. After inclusion the contract's code is read back.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from stellar_sdk import Address, InvokeHostFunction, Keypair, StrKey, TransactionEnvelope
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.auth import _get_address_credentials

from app.blockchain.config import get_network
from app.core.config import get_settings
from app.core.exceptions import ValidationFailed

# passkey-kit's canonical deterministic deployer (DEFAULT_DEPLOYER_SEED = "kalepail"). Its secret is public by
# design: it only salts deployments and signs their authorization entry. It never controls a wallet.
DEPLOYER = Keypair.from_raw_ed25519_seed(hashlib.sha256(b"kalepail").digest()).public_key


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def derive_contract_id(key_id: bytes, deployer: str = DEPLOYER) -> str:
    """The wallet address passkey-kit derives for a credential id (``salt = sha256(keyId)``)."""
    preimage = stellar_xdr.ContractIDPreimage(
        type=stellar_xdr.ContractIDPreimageType.CONTRACT_ID_PREIMAGE_FROM_ADDRESS,
        from_address=stellar_xdr.ContractIDPreimageFromAddress(
            address=Address(deployer).to_xdr_sc_address(),
            salt=stellar_xdr.Uint256(hashlib.sha256(key_id).digest()),
        ),
    )
    return _contract_id(preimage)


def _contract_id(preimage: stellar_xdr.ContractIDPreimage) -> str:
    network_id = hashlib.sha256(get_network().passphrase.encode()).digest()
    hash_preimage = stellar_xdr.HashIDPreimage(
        type=stellar_xdr.EnvelopeType.ENVELOPE_TYPE_CONTRACT_ID,
        contract_id=stellar_xdr.HashIDPreimageContractID(
            network_id=stellar_xdr.Hash(network_id), contract_id_preimage=preimage
        ),
    )
    return StrKey.encode_contract(hashlib.sha256(hash_preimage.to_xdr_bytes()).digest())


@dataclass(frozen=True)
class Deployment:
    contract_id: str
    key_id: str  # base64url credential id
    public_key: str  # hex, 65-byte uncompressed P-256 point
    wasm_hash: str
    host_function: stellar_xdr.HostFunction
    auth: list[stellar_xdr.SorobanAuthorizationEntry]


def _signer_fields(signer: stellar_xdr.SCVal) -> tuple[bytes, bytes]:
    """``Signer::Secp256r1(key_id, public_key, expiration, limits, storage)`` → (key id, public key)."""
    if signer.type != stellar_xdr.SCValType.SCV_VEC or not signer.vec:
        raise ValidationFailed("The wallet deployment does not set a passkey signer.")
    items = signer.vec.sc_vec
    if (
        len(items) < 3
        or items[0].type != stellar_xdr.SCValType.SCV_SYMBOL
        or items[0].sym is None
        or items[0].sym.sc_symbol != b"Secp256r1"
        or items[1].bytes is None
        or items[2].bytes is None
    ):
        raise ValidationFailed("The wallet deployment does not set a passkey signer.")
    return items[1].bytes.sc_bytes, items[2].bytes.sc_bytes


def check_deployment(carrier_xdr: str, key_id: str, public_key: str) -> Deployment:
    """Validates the browser-built deployment and returns the host function and authorization to relay.

    ``key_id`` is the base64url credential id and ``public_key`` the hex (or base64url) uncompressed P-256 key
    the browser registered; both must be the ones the deployment installs as the wallet's signer."""
    network = get_network()
    expected_wasm = get_settings().passkey_wallet_wasm_hash.lower()
    try:
        key_id_bytes = b64url_decode(key_id)
        pk = bytes.fromhex(public_key) if len(public_key) == 130 else b64url_decode(public_key)
        envelope = TransactionEnvelope.from_xdr(carrier_xdr, network.passphrase)
    except Exception as exc:
        raise ValidationFailed("The wallet deployment could not be decoded.") from exc
    if not key_id_bytes or len(pk) != 65 or pk[0] != 0x04:
        raise ValidationFailed("The passkey public key is not an uncompressed P-256 key.")
    operations = envelope.transaction.operations
    if len(operations) != 1 or not isinstance(operations[0], InvokeHostFunction):
        raise ValidationFailed("The wallet deployment must be a single contract creation.")
    op = operations[0]
    host = op.host_function
    create = host.create_contract_v2
    if host.type != stellar_xdr.HostFunctionType.HOST_FUNCTION_TYPE_CREATE_CONTRACT_V2 or create is None:
        raise ValidationFailed("The wallet deployment must be a single contract creation.")
    preimage = create.contract_id_preimage
    from_address = preimage.from_address
    if from_address is None or Address.from_xdr_sc_address(from_address.address).address != DEPLOYER:
        raise ValidationFailed("The wallet deployment uses an unexpected deployer.")
    if from_address.salt.uint256 != hashlib.sha256(key_id_bytes).digest():
        raise ValidationFailed("The wallet deployment is not derived from this passkey.")
    wasm_hash = create.executable.wasm_hash
    if wasm_hash is None or wasm_hash.hash.hex() != expected_wasm:
        raise ValidationFailed("The wallet deployment uses unexpected contract code.")
    if not create.constructor_args:
        raise ValidationFailed("The wallet deployment does not set a passkey signer.")
    signer_key_id, signer_public_key = _signer_fields(create.constructor_args[0])
    if signer_key_id != key_id_bytes or signer_public_key != pk:
        raise ValidationFailed("The wallet deployment installs a different passkey.")
    if len(op.auth) != 1:
        raise ValidationFailed("The wallet deployment must carry exactly the deployer's authorization.")
    entry = op.auth[0]
    credentials = _get_address_credentials(entry.credentials)
    if credentials is None or Address.from_xdr_sc_address(credentials.address).address != DEPLOYER:
        raise ValidationFailed("The wallet deployment must carry exactly the deployer's authorization.")
    function = entry.root_invocation.function
    if (
        function.type
        != stellar_xdr.SorobanAuthorizedFunctionType.SOROBAN_AUTHORIZED_FUNCTION_TYPE_CREATE_CONTRACT_V2_HOST_FN
        or function.create_contract_v2_host_fn is None
        or function.create_contract_v2_host_fn.to_xdr() != create.to_xdr()
        or entry.root_invocation.sub_invocations
    ):
        raise ValidationFailed("The deployer's authorization does not match the wallet deployment.")
    return Deployment(
        contract_id=_contract_id(preimage),
        key_id=key_id,
        public_key=pk.hex(),
        wasm_hash=expected_wasm,
        host_function=host,
        auth=list(op.auth),
    )
