"""Bitstring Status List v1.0 encoding: a GZIP-compressed bitstring, multibase base64url (``u…``) encoded.

Bit 0 is the left-most (most significant) bit of the first byte. A set bit means the credential holding that
``statusListIndex`` is revoked. The list is 131,072 entries long, the specification's minimum, so a single
list does not reveal how many credentials exist.
"""

from __future__ import annotations

import gzip
from collections.abc import Iterable

from app.modules.credentials.multibase import decode_base64url, encode_base64url

LIST_LENGTH = 131_072  # entries (16 KiB)


class StatusListError(ValueError):
    pass


def encode(revoked: Iterable[int], length: int = LIST_LENGTH) -> str:
    bits = bytearray(length // 8)
    for index in revoked:
        if not 0 <= index < length:
            raise StatusListError(f"Status index {index} is outside the list")
        bits[index // 8] |= 0x80 >> (index % 8)
    return encode_base64url(gzip.compress(bytes(bits), mtime=0))


def decode(encoded_list: str) -> bytes:
    try:
        return gzip.decompress(decode_base64url(encoded_list))
    except (OSError, EOFError, ValueError) as exc:
        raise StatusListError("The encoded status list is not valid") from exc


def is_set(bits: bytes, index: int) -> bool:
    if not 0 <= index < len(bits) * 8:
        raise StatusListError(f"Status index {index} is outside the list")
    return bool(bits[index // 8] & (0x80 >> (index % 8)))
