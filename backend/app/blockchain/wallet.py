"""Wallet ownership proof for every kind of Stellar wallet.

Three proofs, one per way a wallet can sign; every challenge is issued for one user and one address, stored in
Redis and consumed on the first verification attempt (single use, replay protection):

* **SEP-10 challenge transaction** (``sep10``, account addresses ``G...``). The server builds a challenge
  transaction (a manage_data op sourced from the user's address, with a random nonce and short time bounds) and
  signs it with a server key that never holds funds. The user's wallet signs it; both signatures are verified
  offline. The challenge is **never submitted** to the network.
* **SEP-53 signed message** (``sep53``, ``G...``). For wallets that sign messages rather than transactions, or
  cannot be told which network to sign for: the wallet signs ``sha256("Stellar Signed Message:\\n" + message)``
  with the account's ed25519 key. The message names the address, the network and a random nonce.
* **SEP-45 web authentication** (``sep45``, contract accounts ``C...`` such as passkey smart wallets). The
  challenge is a pair of Soroban authorization entries for ``web_auth_verify`` on BountyFlow's web auth contract
  (``contracts/web_auth``): one signed by the server key, one for the wallet. The wallet signs its entry with
  its own signer (a passkey), and the server verifies both by *simulating* the call: it only succeeds when the
  wallet's ``__check_auth`` accepts the signature. Nothing is submitted. This is the same authorization path the
  wallet uses for payments, so it proves control however the wallet's signers are configured.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

from stellar_sdk import Address, Keypair, TransactionEnvelope
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.auth import _get_address_credentials
from stellar_sdk.exceptions import BadSignatureError
from stellar_sdk.sep.exceptions import InvalidSep10ChallengeError, InvalidSep45ChallengeError
from stellar_sdk.sep.stellar_soroban_web_authentication import (
    build_challenge_authorization_entries_async,
    read_challenge_authorization_entries,
    verify_challenge_authorization_entries_async,
)
from stellar_sdk.sep.stellar_web_authentication import (
    build_challenge_transaction,
    verify_challenge_transaction_signed_by_client_master_key,
)
from stellar_sdk.soroban_server_async import SorobanServerAsync
from stellar_sdk.strkey import StrKey

from app.blockchain.client import get_soroban
from app.blockchain.config import get_network
from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailable, ValidationFailed
from app.core.logging import get_logger

logger = get_logger(__name__)

WEB_AUTH_DOMAIN = "api.bountyflow.local"

ProofMethod = Literal["sep10", "sep53", "sep45"]


@lru_cache
def server_keypair() -> Keypair:
    settings = get_settings()
    if settings.wallet_challenge_signing_secret:
        return Keypair.from_secret(settings.wallet_challenge_signing_secret)
    # Development fallback: derive a stable key from JWT_SECRET (production requires an explicit secret).
    seed = hashlib.sha256(("wallet-challenge:" + settings.jwt_secret).encode()).digest()
    return Keypair.from_raw_ed25519_seed(seed)


def validate_address(address: str, *, allow_contract: bool = False) -> str:
    address = address.strip()
    if StrKey.is_valid_ed25519_public_key(address):
        return address
    if allow_contract and StrKey.is_valid_contract(address):
        return address
    raise ValidationFailed(
        "Invalid Stellar public address.",
        details=[
            {
                "field": "public_address",
                "message": "Must be a G... or C... address" if allow_contract else "Must be a G... address",
            }
        ],
    )


def default_method(address: str) -> ProofMethod:
    return "sep45" if StrKey.is_valid_contract(address) else "sep10"


@dataclass(frozen=True)
class Challenge:
    method: ProofMethod
    expires_at: datetime
    xdr: str | None = None  # sep10: the challenge transaction to sign
    message: str | None = None  # sep53: the text to sign
    authorization_entries: str | None = (
        None  # sep45: SorobanAuthorizationEntries to sign the wallet's entry of
    )


async def _store(user_id: str, address: str, record: dict[str, Any], ttl: int) -> None:
    try:
        await get_redis().set(keys.wallet_challenge(user_id, address), json.dumps(record), ex=ttl)
    except Exception as exc:
        raise ServiceUnavailable("Wallet verification is temporarily unavailable.") from exc


async def _consume(user_id: str, address: str) -> dict[str, Any]:
    try:
        raw = await get_redis().getdel(keys.wallet_challenge(user_id, address))
    except Exception as exc:
        raise ServiceUnavailable("Wallet verification is temporarily unavailable.") from exc
    if raw is None:
        raise ValidationFailed("The challenge has expired or was already used. Request a new one.")
    record: dict[str, Any] = json.loads(raw)
    return record


# --- SEP-10: challenge transaction ------------------------------------------------------------------------


async def create_challenge(user_id: str, address: str) -> Challenge:
    settings = get_settings()
    network = get_network()
    address = validate_address(address)
    ttl = settings.wallet_challenge_ttl
    xdr = build_challenge_transaction(
        server_secret=server_keypair().secret,
        client_account_id=address,
        home_domain=settings.wallet_challenge_home_domain,
        web_auth_domain=WEB_AUTH_DOMAIN,
        network_passphrase=network.passphrase,
        timeout=ttl,
    )
    envelope = TransactionEnvelope.from_xdr(xdr, network.passphrase)
    await _store(user_id, address, {"method": "sep10", "hash": envelope.hash_hex(), "xdr": xdr}, ttl)
    return Challenge(method="sep10", xdr=xdr, expires_at=datetime.now(UTC) + timedelta(seconds=ttl))


def _verify_sep10(record: dict[str, Any], address: str, signed_xdr: str) -> None:
    settings = get_settings()
    network = get_network()
    try:
        envelope = TransactionEnvelope.from_xdr(signed_xdr, network.passphrase)
    except Exception as exc:
        raise ValidationFailed("The signed challenge could not be decoded.") from exc
    if envelope.hash_hex() != record.get("hash"):
        raise ValidationFailed("The signed challenge does not match the issued challenge.")
    try:
        verify_challenge_transaction_signed_by_client_master_key(
            challenge_transaction=signed_xdr,
            server_account_id=server_keypair().public_key,
            home_domains=settings.wallet_challenge_home_domain,
            web_auth_domain=WEB_AUTH_DOMAIN,
            network_passphrase=network.passphrase,
        )
    except InvalidSep10ChallengeError as exc:
        raise ValidationFailed(f"Wallet signature verification failed: {exc}") from exc


async def verify_challenge(user_id: str, address: str, signed_xdr: str) -> None:
    """Consumes the issued SEP-10 challenge and verifies the wallet's signature; raises ValidationFailed
    otherwise."""
    address = validate_address(address)
    record = await _consume(user_id, address)
    if record.get("method", "sep10") != "sep10":
        raise ValidationFailed("This challenge must be answered with a signed transaction.")
    _verify_sep10(record, address, signed_xdr)


# --- SEP-53: signed message ---------------------------------------------------------------------------------


def challenge_message(address: str, nonce: str, expires_at: datetime) -> str:
    settings = get_settings()
    return (
        "BountyFlow wallet verification\n"
        f"Address: {address}\n"
        f"Network: {get_network().network}\n"
        f"Domain: {settings.wallet_challenge_home_domain}\n"
        f"Nonce: {nonce}\n"
        f"Expires: {expires_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )


async def create_message_challenge(user_id: str, address: str) -> Challenge:
    ttl = get_settings().wallet_challenge_ttl
    address = validate_address(address)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    message = challenge_message(address, secrets.token_hex(24), expires_at)
    await _store(user_id, address, {"method": "sep53", "message": message}, ttl)
    return Challenge(method="sep53", message=message, expires_at=expires_at)


def _decode_signature(value: str) -> bytes:
    value = value.strip()
    if len(value) == 128:
        try:
            return bytes.fromhex(value)
        except ValueError:
            pass
    padded = value + "=" * (-len(value) % 4)
    try:
        if "-" in value or "_" in value:
            return base64.urlsafe_b64decode(padded)
        return base64.b64decode(padded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationFailed("The signed message could not be decoded.") from exc


def _verify_sep53(record: dict[str, Any], address: str, signed_message: str) -> None:
    signature = _decode_signature(signed_message)
    if len(signature) != 64:
        raise ValidationFailed("The signed message could not be decoded.")
    try:
        Keypair.from_public_key(address).verify_message(str(record["message"]), signature)
    except BadSignatureError as exc:
        raise ValidationFailed("The message signature does not match this address.") from exc


# --- SEP-45: contract accounts ------------------------------------------------------------------------------


def web_auth_contract() -> str:
    contract = get_settings().web_auth_contract_id
    if not contract:
        raise ServiceUnavailable(
            "Smart-wallet verification is not configured on this server (WEB_AUTH_CONTRACT_ID).",
            code="web_auth_unavailable",
        )
    return contract


def sep45_server() -> SorobanServerAsync:
    """The RPC used to simulate SEP-45 challenges (tests replace it)."""
    return get_soroban()


async def create_contract_challenge(user_id: str, address: str) -> Challenge:
    settings = get_settings()
    network = get_network()
    address = validate_address(address, allow_contract=True)
    if not StrKey.is_valid_contract(address):
        raise ValidationFailed("Only contract accounts (C...) use this proof.")
    ttl = settings.wallet_challenge_ttl
    nonce = secrets.token_hex(24)
    try:
        entries = await build_challenge_authorization_entries_async(
            soroban_server=sep45_server(),
            server_secret=server_keypair().secret,
            client_account_id=address,
            home_domain=settings.wallet_challenge_home_domain,
            web_auth_domain=WEB_AUTH_DOMAIN,
            web_auth_contract=web_auth_contract(),
            network_passphrase=network.passphrase,
            nonce=nonce,
            expire_in_ledgers=max(12, ttl // 5),
        )
    except ValueError as exc:
        logger.warning("sep45_challenge_failed", error=str(exc))
        raise ServiceUnavailable(
            "The wallet challenge could not be prepared on the network. Please try again."
        ) from exc
    await _store(user_id, address, {"method": "sep45", "nonce": nonce, "entries": entries}, ttl)
    return Challenge(
        method="sep45", authorization_entries=entries, expires_at=datetime.now(UTC) + timedelta(seconds=ttl)
    )


def _merge_signed_entries(issued_xdr: str, signed_xdr: str, address: str) -> str:
    """The server's own (already signed) entry comes from the issued challenge; only the client's entry is taken
    from the wallet, and it must authorize exactly the issued invocation for exactly this address."""
    issued = stellar_xdr.SorobanAuthorizationEntries.from_xdr(issued_xdr).soroban_authorization_entries
    try:
        signed = stellar_xdr.SorobanAuthorizationEntries.from_xdr(signed_xdr).soroban_authorization_entries
    except Exception:
        try:  # a single signed entry is accepted too
            signed = [stellar_xdr.SorobanAuthorizationEntry.from_xdr(signed_xdr)]
        except Exception as exc:
            raise ValidationFailed("The signed challenge could not be decoded.") from exc
    root = issued[0].root_invocation.to_xdr()
    client_entry = None
    for entry in signed:
        credentials = _get_address_credentials(entry.credentials)
        if credentials is None:
            continue
        if Address.from_xdr_sc_address(credentials.address).address != address:
            continue
        if entry.root_invocation.to_xdr() != root:
            raise ValidationFailed("The signed challenge does not match the issued challenge.")
        if credentials.signature.type == stellar_xdr.SCValType.SCV_VOID:
            raise ValidationFailed("The challenge has not been signed by the wallet.")
        client_entry = entry
    if client_entry is None:
        raise ValidationFailed("The signed challenge has no authorization from this wallet.")
    merged = []
    for entry in issued:
        credentials = _get_address_credentials(entry.credentials)
        is_client = (
            credentials is not None and Address.from_xdr_sc_address(credentials.address).address == address
        )
        merged.append(client_entry if is_client else entry)
    return stellar_xdr.SorobanAuthorizationEntries(merged).to_xdr()


async def _verify_sep45(record: dict[str, Any], address: str, signed_entries: str) -> None:
    settings = get_settings()
    network = get_network()
    merged = _merge_signed_entries(str(record["entries"]), signed_entries, address)
    try:
        parsed = read_challenge_authorization_entries(
            merged,
            server_account_id=server_keypair().public_key,
            home_domains=settings.wallet_challenge_home_domain,
            web_auth_domain=WEB_AUTH_DOMAIN,
            web_auth_contract=web_auth_contract(),
        )
    except InvalidSep45ChallengeError as exc:
        raise ValidationFailed(f"Wallet signature verification failed: {exc}") from exc
    if parsed.nonce != record.get("nonce") or parsed.client_account_id != address:
        raise ValidationFailed("The signed challenge does not match the issued challenge.")
    try:
        await verify_challenge_authorization_entries_async(
            sep45_server(),
            merged,
            server_account_id=server_keypair().public_key,
            home_domains=settings.wallet_challenge_home_domain,
            web_auth_domain=WEB_AUTH_DOMAIN,
            web_auth_contract=web_auth_contract(),
            network_passphrase=network.passphrase,
        )
    except InvalidSep45ChallengeError as exc:
        logger.info("sep45_verification_failed", address=address, error=str(exc)[:300])
        raise ValidationFailed(
            "The wallet did not authorize the challenge. Sign it again with the wallet."
        ) from exc


# --- Entry points -------------------------------------------------------------------------------------------


async def issue_challenge(user_id: str, address: str, method: ProofMethod | None = None) -> Challenge:
    address = validate_address(address, allow_contract=True)
    method = method or default_method(address)
    if StrKey.is_valid_contract(address) != (method == "sep45"):
        raise ValidationFailed(
            "Contract accounts (C...) prove ownership with a contract authorization; accounts (G...) sign a "
            "transaction or a message.",
            details=[{"field": "method", "message": "Not available for this address"}],
        )
    if method == "sep45":
        return await create_contract_challenge(user_id, address)
    if method == "sep53":
        return await create_message_challenge(user_id, address)
    return await create_challenge(user_id, address)


async def verify_proof(
    user_id: str,
    address: str,
    *,
    signed_challenge_xdr: str | None = None,
    signed_message: str | None = None,
    signed_authorization_entries: str | None = None,
) -> ProofMethod:
    """Consumes the issued challenge and checks the answer for its method. Returns the method that proved
    ownership; raises ValidationFailed otherwise (the challenge is used up either way)."""
    address = validate_address(address, allow_contract=True)
    record = await _consume(user_id, address)
    method: ProofMethod = record.get("method", "sep10")
    if method == "sep10":
        if not signed_challenge_xdr:
            raise ValidationFailed("Sign the challenge transaction to verify this wallet.")
        _verify_sep10(record, address, signed_challenge_xdr)
    elif method == "sep53":
        if not signed_message:
            raise ValidationFailed("Sign the challenge message to verify this wallet.")
        _verify_sep53(record, address, signed_message)
    else:
        if not signed_authorization_entries:
            raise ValidationFailed("Authorize the challenge with the wallet to verify it.")
        await _verify_sep45(record, address, signed_authorization_entries)
    return method


def sep53_signature(keypair: Keypair, message: str) -> str:
    """Base64 SEP-53 signature (used by tests and scripts; wallets sign in the browser)."""
    return base64.b64encode(keypair.sign_message(message)).decode()


__all__ = [
    "WEB_AUTH_DOMAIN",
    "Challenge",
    "ProofMethod",
    "challenge_message",
    "create_challenge",
    "default_method",
    "issue_challenge",
    "sep45_server",
    "sep53_signature",
    "server_keypair",
    "validate_address",
    "verify_challenge",
    "verify_proof",
    "web_auth_contract",
]
