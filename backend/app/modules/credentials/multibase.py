"""Multibase and Multikey encodings used by Data Integrity proofs and DID documents.

* ``z`` + base58btc: proof values and Multikey public keys (``z6Mk…`` for Ed25519).
* ``u`` + base64url without padding: the Bitstring Status List ``encodedList``.
"""

from __future__ import annotations

import base64

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {c: i for i, c in enumerate(BASE58_ALPHABET)}

# Multicodec varint prefixes.
ED25519_PUB = b"\xed\x01"
ED25519_PRIV = b"\x80\x26"


class MultibaseError(ValueError):
    pass


def b58encode(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    out = ""
    while number:
        number, rem = divmod(number, 58)
        out = BASE58_ALPHABET[rem] + out
    pad = len(data) - len(data.lstrip(b"\0"))
    return "1" * pad + out


def b58decode(text: str) -> bytes:
    number = 0
    for char in text:
        if char not in _BASE58_INDEX:
            raise MultibaseError("Invalid base58btc character")
        number = number * 58 + _BASE58_INDEX[char]
    pad = len(text) - len(text.lstrip("1"))
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * pad + body


def encode_base58btc(data: bytes) -> str:
    return "z" + b58encode(data)


def decode_base58btc(text: str) -> bytes:
    if not isinstance(text, str) or not text.startswith("z") or len(text) < 2:
        raise MultibaseError("Expected a base58btc multibase value (z…)")
    return b58decode(text[1:])


def encode_base64url(data: bytes) -> str:
    return "u" + base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def decode_base64url(text: str) -> bytes:
    if not isinstance(text, str) or not text.startswith("u"):
        raise MultibaseError("Expected a base64url multibase value (u…)")
    body = text[1:]
    try:
        return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError as exc:
        raise MultibaseError("Invalid base64url value") from exc


def ed25519_public_multikey(public_key: bytes) -> str:
    """Multikey ``publicKeyMultibase`` for a 32-byte Ed25519 public key (``z6Mk…``)."""
    assert len(public_key) == 32
    return encode_base58btc(ED25519_PUB + public_key)


def ed25519_public_from_multikey(value: str) -> bytes:
    raw = decode_base58btc(value)
    if len(raw) != 34 or not raw.startswith(ED25519_PUB):
        raise MultibaseError("Not an Ed25519 Multikey public key")
    return raw[2:]


def ed25519_seed_from_multikey(value: str) -> bytes:
    """The 32-byte seed of an Ed25519 Multikey secret key (``secretKeyMultibase``)."""
    raw = decode_base58btc(value)
    if len(raw) != 34 or not raw.startswith(ED25519_PRIV):
        raise MultibaseError("Not an Ed25519 Multikey secret key")
    return raw[2:]
