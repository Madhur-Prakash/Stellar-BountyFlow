"""Wallet ownership proof using a SEP-10 challenge transaction.

The server builds a challenge transaction (a manage_data op sourced from the user's address, with a random
nonce and short time bounds) and signs it with a server key that never holds funds. The user's wallet signs it;
we verify both signatures offline. The challenge is **never submitted** to the network. Each challenge is stored
in Redis and consumed on first verification (replay protection).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from stellar_sdk import Keypair, TransactionEnvelope
from stellar_sdk.sep.exceptions import InvalidSep10ChallengeError
from stellar_sdk.sep.stellar_web_authentication import (
    build_challenge_transaction,
    verify_challenge_transaction_signed_by_client_master_key,
)
from stellar_sdk.strkey import StrKey

from app.blockchain.config import get_network
from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailable, ValidationFailed

WEB_AUTH_DOMAIN = "api.bountyflow.local"


@lru_cache
def server_keypair() -> Keypair:
    settings = get_settings()
    if settings.wallet_challenge_signing_secret:
        return Keypair.from_secret(settings.wallet_challenge_signing_secret)
    # Development fallback: derive a stable key from JWT_SECRET (production requires an explicit secret).
    seed = hashlib.sha256(("wallet-challenge:" + settings.jwt_secret).encode()).digest()
    return Keypair.from_raw_ed25519_seed(seed)


def validate_address(address: str) -> str:
    address = address.strip()
    if not StrKey.is_valid_ed25519_public_key(address):
        raise ValidationFailed(
            "Invalid Stellar public address.",
            details=[{"field": "public_address", "message": "Must be a G... address"}],
        )
    return address


@dataclass(frozen=True)
class Challenge:
    xdr: str
    expires_at: datetime


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
    record = {"hash": envelope.hash_hex(), "xdr": xdr}
    try:
        await get_redis().set(keys.wallet_challenge(user_id, address), json.dumps(record), ex=ttl)
    except Exception as exc:
        raise ServiceUnavailable("Wallet verification is temporarily unavailable.") from exc
    return Challenge(xdr=xdr, expires_at=datetime.now(UTC) + timedelta(seconds=ttl))


async def verify_challenge(user_id: str, address: str, signed_xdr: str) -> None:
    """Consumes the issued challenge and verifies the wallet's signature; raises ValidationFailed otherwise."""
    settings = get_settings()
    network = get_network()
    address = validate_address(address)
    try:
        raw = await get_redis().getdel(keys.wallet_challenge(user_id, address))
    except Exception as exc:
        raise ServiceUnavailable("Wallet verification is temporarily unavailable.") from exc
    if raw is None:
        raise ValidationFailed("The challenge has expired or was already used. Request a new one.")
    record = json.loads(raw)

    try:
        envelope = TransactionEnvelope.from_xdr(signed_xdr, network.passphrase)
    except Exception as exc:
        raise ValidationFailed("The signed challenge could not be decoded.") from exc
    if envelope.hash_hex() != record["hash"]:
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
