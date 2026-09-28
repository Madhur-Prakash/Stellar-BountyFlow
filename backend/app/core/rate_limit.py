"""Redis fixed-window rate limiting as a FastAPI dependency.

When Redis is unavailable the limiter fails open (so an outage does not lock every user out) and logs
`rate_limit_unavailable`; production deployments should alert on that log event.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request

from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.exceptions import RateLimited
from app.core.logging import get_logger

logger = get_logger(__name__)

# user_sessions.ip_address is VARCHAR(64); the derived value is also used in Redis keys.
MAX_CLIENT_IP_LENGTH = 64


def client_ip(request: Request) -> str:
    """The client address used for rate limiting, view counting and session records.

    Security: proxies *append* to X-Forwarded-For, so only the entries added by our own trusted proxies (the
    right-most ``TRUSTED_PROXY_HOPS``) can be believed; the left-most value is whatever the client sent. Taking
    the first hop let anyone mint a fresh rate-limit bucket per request by rotating that header.
    """
    hops = get_settings().trusted_proxy_hops
    forwarded = request.headers.get("x-forwarded-for")
    if hops > 0 and forwarded:
        entries = [part.strip() for part in forwarded.split(",") if part.strip()]
        if entries:
            return entries[-min(hops, len(entries))][:MAX_CLIENT_IP_LENGTH]
    host = request.client.host if request.client else "unknown"
    return host[:MAX_CLIENT_IP_LENGTH]


async def hit(scope: str, identity: str, limit: int, window_seconds: int) -> None:
    window = int(time.time() // window_seconds)
    key = keys.rate_limit(scope, identity, window)
    try:
        redis = get_redis()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds + 1)
            count, _ = await pipe.execute()
    except Exception as exc:
        logger.warning("rate_limit_unavailable", scope=scope, error=str(exc))
        return
    if int(count) > limit:
        retry_after = window_seconds - int(time.time() % window_seconds)
        raise RateLimited(retry_after=max(retry_after, 1))


def rate_limit(scope: str, limit: int, window_seconds: int) -> Callable[[Request], Awaitable[None]]:
    async def dependency(request: Request) -> None:
        await hit(scope, client_ip(request), limit, window_seconds)

    return dependency
