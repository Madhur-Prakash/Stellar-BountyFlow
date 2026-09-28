"""Password hashing (Argon2id), JWT access tokens, opaque token generation, and CSRF helpers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.exceptions import NotAuthenticated, TokenExpired

# Argon2id with OWASP-recommended parameters (m=19 MiB, t=2, p=1) or stronger.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)

ACCESS_COOKIE = "bf_access"
REFRESH_COOKIE = "bf_refresh"
CSRF_COOKIE = "bf_csrf"
CSRF_HEADER = "X-CSRF-Token"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# Security: an Argon2id computation (64 MiB, t=3) takes ~100 ms of CPU. Run inline in an async handler it
# stalls the event loop for every in-flight request, turning unauthenticated login/register traffic into a cheap
# denial of service. Request handlers use the async wrappers below, which run the work on a small dedicated
# pool (argon2-cffi releases the GIL). The pool size also caps concurrent Argon2 memory (4 x 64 MiB).
_PASSWORD_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="argon2")


async def hash_password_async(password: str) -> str:
    return await asyncio.get_running_loop().run_in_executor(_PASSWORD_POOL, hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    return await asyncio.get_running_loop().run_in_executor(
        _PASSWORD_POOL, verify_password, password_hash, password
    )


# A precomputed hash used to equalise timing when a login email does not exist.
DUMMY_PASSWORD_HASH = _hasher.hash("timing-equalisation-placeholder")


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash opaque tokens (refresh, verification, reset) before storing them. SHA-256 is appropriate
    because the tokens are high-entropy random values, not user-chosen secrets."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    role: str


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl)).timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": settings.app_name.lower(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> AccessClaims:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.app_name.lower(),
            options={"require": ["exp", "sub", "sid", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired("Access token expired.") from exc
    except jwt.PyJWTError as exc:
        raise NotAuthenticated("Invalid access token.") from exc
    if payload.get("type") != "access":
        raise NotAuthenticated("Invalid access token.")
    try:
        return AccessClaims(
            user_id=uuid.UUID(payload["sub"]),
            session_id=uuid.UUID(payload["sid"]),
            role=str(payload.get("role", "USER")),
        )
    except (ValueError, KeyError) as exc:
        raise NotAuthenticated("Invalid access token.") from exc


def split_refresh_token(raw: str) -> tuple[uuid.UUID, str]:
    """Refresh tokens are formatted as ``<session_id>.<secret>``."""
    try:
        sid, secret = raw.split(".", 1)
        return uuid.UUID(sid), secret
    except ValueError as exc:
        raise NotAuthenticated("Invalid refresh token.") from exc
