"""Redis client wrapper. Cache failures are logged and swallowed so they never corrupt application state."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            health_check_interval=30,
        )
    return _client


def set_redis(client: Redis) -> None:
    """Used by tests (fakeredis)."""
    global _client
    _client = client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


async def check_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def cache_get_json(key: str) -> Any | None:
    try:
        raw = await get_redis().get(key)
    except Exception as exc:
        logger.warning("cache_get_failed", key=key, error=str(exc))
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def cache_set_json(key: str, value: Any, ttl: int) -> None:
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:
        logger.warning("cache_set_failed", key=key, error=str(exc))


async def cache_delete(*keys: str) -> None:
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception as exc:
        logger.warning("cache_delete_failed", keys=keys, error=str(exc))


async def cached_json(key: str, ttl: int, loader: Callable[[], Awaitable[T]]) -> T:
    """Read-through cache for JSON-serialisable values."""
    hit = await cache_get_json(key)
    if hit is not None:
        return hit
    value = await loader()
    await cache_set_json(key, value, ttl)
    return value
