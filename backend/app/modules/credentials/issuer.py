"""The credential issuer: a ``did:web`` identity for the site and its Ed25519 signing key.

The key comes only from ``CREDENTIAL_ISSUER_SECRET`` (a Stellar secret seed, i.e. an Ed25519 seed); without it the
feature is off. The DID document is served at ``/.well-known/did.json`` of the issuer domain (the API serves it,
and the frontend's nginx / Vite proxy passes it through), with the key as a Multikey ``assertionMethod``.
Subjects are identified by the Stellar account that was paid, as ``did:pkh:stellar:<network>:<G…>`` (CAIP-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlsplit

from stellar_sdk import Keypair

from app.core.config import get_settings
from app.core.logging import get_logger
from app.modules.credentials.multibase import ed25519_public_multikey

logger = get_logger(__name__)

VC_CONTEXT = "https://www.w3.org/ns/credentials/v2"
DID_CONTEXT = "https://www.w3.org/ns/did/v1"
MULTIKEY_CONTEXT = "https://w3id.org/security/multikey/v1"
ISSUER_NAME = "BountyFlow"


@dataclass(frozen=True)
class Issuer:
    did: str
    key_id: str
    public_key: bytes
    public_multikey: str
    seed: bytes
    origin: str  # public site origin, e.g. https://bountyflow.example
    api_base: str  # public API base URL, e.g. https://bountyflow.example/api/v1

    @property
    def status_list_url(self) -> str:
        return f"{self.api_base}/credentials/status/revocation"

    @property
    def did_document_url(self) -> str:
        return f"{self.origin}/.well-known/did.json"


def did_web(domain: str) -> str:
    """``did:web`` for a host (a port is percent-encoded, as the did:web method requires)."""
    return "did:web:" + quote(domain.strip().lower(), safe=".-")


def subject_did(address: str, network: str) -> str:
    """CAIP-10 ``did:pkh`` for a Stellar account (CAIP-2 references: ``pubnet`` and ``testnet``)."""
    reference = "pubnet" if network == "mainnet" else network
    return f"did:pkh:stellar:{reference}:{address}"


def address_from_subject(did: str) -> tuple[str, str] | None:
    """``(network reference, G… address)`` of a Stellar ``did:pkh``, else None."""
    parts = did.split(":") if isinstance(did, str) else []
    if len(parts) != 5 or parts[:3] != ["did", "pkh", "stellar"]:
        return None
    return parts[3], parts[4]


@lru_cache(maxsize=4)
def _build(secret: str, domain: str, origin: str, api_base: str) -> Issuer | None:
    try:
        keypair = Keypair.from_secret(secret)
    except Exception:
        logger.error("credential_issuer_secret_invalid")
        return None
    public_key = keypair.raw_public_key()
    did = did_web(domain)
    multikey = ed25519_public_multikey(public_key)
    return Issuer(
        did=did,
        key_id=f"{did}#{multikey}",
        public_key=public_key,
        public_multikey=multikey,
        seed=keypair.raw_secret_key(),
        origin=origin,
        api_base=api_base,
    )


def get_issuer() -> Issuer | None:
    settings = get_settings()
    secret = (settings.credential_issuer_secret or "").strip()
    if not secret:
        return None
    frontend = urlsplit(settings.frontend_url)
    domain = settings.credential_issuer_domain or frontend.netloc
    origin = f"{frontend.scheme}://{frontend.netloc}"
    public_api = getattr(settings, "public_api_url", None) or origin
    return _build(secret, domain, origin, public_api.rstrip("/") + settings.api_prefix)


def did_document(issuer: Issuer) -> dict[str, Any]:
    method = {
        "id": issuer.key_id,
        "type": "Multikey",
        "controller": issuer.did,
        "publicKeyMultibase": issuer.public_multikey,
    }
    return {
        "@context": [DID_CONTEXT, MULTIKEY_CONTEXT],
        "id": issuer.did,
        "verificationMethod": [method],
        "assertionMethod": [issuer.key_id],
        "service": [
            {"id": f"{issuer.did}#site", "type": "LinkedDomains", "serviceEndpoint": issuer.origin},
        ],
    }
