"""W3C Data Integrity proofs with the ``eddsa-jcs-2022`` cryptosuite (VC Data Integrity EdDSA Cryptosuites v1.0).

Signing (section 3.3 of the cryptosuite spec):

1. proofConfig = the proof options (type, cryptosuite, created, verificationMethod, proofPurpose) plus the
   document's ``@context``.
2. hashData = SHA-256(JCS(proofConfig)) || SHA-256(JCS(document without ``proof``)).
3. proofValue = ``z`` + base58btc(Ed25519 signature of hashData).

JCS (RFC 8785) replaces JSON-LD canonicalization, so signing and verifying never fetch a remote context.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from stellar_sdk import Keypair
from stellar_sdk.exceptions import BadSignatureError

from app.modules.credentials.jcs import CanonicalizationError, canonicalize
from app.modules.credentials.multibase import MultibaseError, decode_base58btc, encode_base58btc

PROOF_TYPE = "DataIntegrityProof"
CRYPTOSUITE = "eddsa-jcs-2022"


class ProofError(ValueError):
    """The proof is malformed, uses another suite, or its signature does not verify."""


def hash_data(unsecured: dict[str, Any], proof_config: dict[str, Any]) -> bytes:
    try:
        return (
            hashlib.sha256(canonicalize(proof_config)).digest()
            + hashlib.sha256(canonicalize(unsecured)).digest()
        )
    except CanonicalizationError as exc:
        raise ProofError(f"The credential cannot be canonicalized: {exc}") from exc


def proof_config(
    unsecured: dict[str, Any],
    *,
    verification_method: str,
    created: str,
    proof_purpose: str = "assertionMethod",
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "type": PROOF_TYPE,
        "cryptosuite": CRYPTOSUITE,
        "created": created,
        "verificationMethod": verification_method,
        "proofPurpose": proof_purpose,
    }
    if "@context" in unsecured:
        config["@context"] = unsecured["@context"]
    return config


def create_proof(
    document: dict[str, Any],
    *,
    seed: bytes,
    verification_method: str,
    created: str,
    proof_purpose: str = "assertionMethod",
) -> dict[str, Any]:
    """A ``DataIntegrityProof`` over ``document`` (any existing ``proof`` is ignored)."""
    unsecured = {k: v for k, v in document.items() if k != "proof"}
    config = proof_config(
        unsecured, verification_method=verification_method, created=created, proof_purpose=proof_purpose
    )
    signature = Keypair.from_raw_ed25519_seed(seed).sign(hash_data(unsecured, config))
    return {**config, "proofValue": encode_base58btc(signature)}


def sign(document: dict[str, Any], *, seed: bytes, verification_method: str, created: str) -> dict[str, Any]:
    unsecured = {k: v for k, v in document.items() if k != "proof"}
    return {
        **unsecured,
        "proof": create_proof(unsecured, seed=seed, verification_method=verification_method, created=created),
    }


@dataclass(frozen=True)
class ProofInfo:
    verification_method: str
    proof_purpose: str
    created: str | None


def read_proof(secured: dict[str, Any]) -> tuple[dict[str, Any], ProofInfo]:
    """The single ``eddsa-jcs-2022`` proof of ``secured`` (proof sets and chains are not issued here)."""
    proof = secured.get("proof")
    if isinstance(proof, list):
        raise ProofError("Credentials with several proofs are not supported.")
    if not isinstance(proof, dict):
        raise ProofError("The credential has no proof.")
    if proof.get("type") != PROOF_TYPE or proof.get("cryptosuite") != CRYPTOSUITE:
        raise ProofError(f"The proof is not a {PROOF_TYPE} with the {CRYPTOSUITE} cryptosuite.")
    method = proof.get("verificationMethod")
    purpose = proof.get("proofPurpose")
    if not isinstance(method, str) or not isinstance(purpose, str):
        raise ProofError("The proof has no verification method or purpose.")
    if not isinstance(proof.get("proofValue"), str):
        raise ProofError("The proof has no proofValue.")
    created = proof.get("created")
    return proof, ProofInfo(method, purpose, created if isinstance(created, str) else None)


def verify_proof(secured: dict[str, Any], public_key: bytes) -> ProofInfo:
    """Verifies the proof with ``public_key`` (32 raw bytes). Raises ProofError when it does not verify."""
    proof, info = read_proof(secured)
    options = {k: v for k, v in proof.items() if k != "proofValue"}
    unsecured = {k: v for k, v in secured.items() if k != "proof"}
    if "@context" in options:
        proof_context = options["@context"]
        doc_context = unsecured.get("@context")
        expected = proof_context if isinstance(proof_context, list) else [proof_context]
        actual = doc_context if isinstance(doc_context, list) else [doc_context]
        if actual[: len(expected)] != expected:
            raise ProofError("The proof's @context does not match the credential's.")
        unsecured["@context"] = proof_context
    try:
        signature = decode_base58btc(proof["proofValue"])
    except MultibaseError as exc:
        raise ProofError("The proofValue is not base58btc multibase.") from exc
    if len(signature) != 64:
        raise ProofError("The proofValue is not an Ed25519 signature.")
    try:
        Keypair.from_raw_ed25519_public_key(public_key).verify(hash_data(unsecured, options), signature)
    except BadSignatureError as exc:
        raise ProofError("The signature does not match the credential.") from exc
    return info
