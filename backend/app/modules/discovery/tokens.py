"""Signed unsubscribe tokens for saved-search alert emails.

A token names one saved search and its owner and carries an HMAC-SHA256 signature, so the link in an email can
turn that search's alerts off without a session. The key is derived from ``JWT_SECRET`` with a fixed purpose
label (domain separation: a token of one kind can never verify as another). Tokens do not expire, because an
unsubscribe link must keep working in an old email; they only ever switch alerts off, which is idempotent.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass

from app.core.config import get_settings

_PURPOSE = b"bountyflow:saved-search-unsubscribe:v1"
_VERSION = "v1"


def _key(secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), _PURPOSE, hashlib.sha256).digest()


def _sign(payload: str, secret: str) -> str:
    digest = hmac.new(_key(secret), payload.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class UnsubscribeClaims:
    saved_search_id: uuid.UUID
    user_id: uuid.UUID


def make_unsubscribe_token(saved_search_id: uuid.UUID, user_id: uuid.UUID, secret: str | None = None) -> str:
    payload = f"{_VERSION}.{saved_search_id.hex}.{user_id.hex}"
    return f"{payload}.{_sign(payload, secret or get_settings().jwt_secret)}"


def read_unsubscribe_token(token: str, secret: str | None = None) -> UnsubscribeClaims | None:
    """The claims of a genuine token, or None for anything malformed or wrongly signed."""
    parts = token.strip().split(".")
    if len(parts) != 4 or parts[0] != _VERSION:
        return None
    payload = ".".join(parts[:3])
    expected = _sign(payload, secret or get_settings().jwt_secret)
    if not hmac.compare_digest(expected.encode("ascii"), parts[3].encode("ascii", errors="replace")):
        return None
    try:
        return UnsubscribeClaims(uuid.UUID(hex=parts[1]), uuid.UUID(hex=parts[2]))
    except ValueError:
        return None
