"""Cache invalidation hooks, called after the database transaction that changed the data has committed."""

from __future__ import annotations

from app.cache import keys
from app.cache.redis import cache_delete, get_redis
from app.core.logging import get_logger

logger = get_logger(__name__)


async def current_generation() -> int:
    try:
        value = await get_redis().get(keys.GEN_BOUNTIES)
        return int(value or 0)
    except Exception:
        return -1  # a sentinel generation that is never written, i.e. bypass the cache


async def invalidate_marketplace() -> None:
    try:
        await get_redis().incr(keys.GEN_BOUNTIES)
    except Exception as exc:
        logger.warning("cache_generation_bump_failed", error=str(exc))


async def invalidate_bounty(bounty_id: str, slug: str | None = None) -> None:
    to_delete = [keys.bounty_detail(bounty_id), keys.public_stats()]
    if slug:
        to_delete.append(keys.bounty_slug(slug))
    await cache_delete(*to_delete)
    await invalidate_marketplace()


async def invalidate_profile(*usernames: str) -> None:
    to_delete: list[str] = []
    for username in usernames:
        if username:
            to_delete += [keys.profile(username), keys.user_stats(username)]
    await cache_delete(*to_delete)


async def invalidate_public_stats() -> None:
    await cache_delete(keys.public_stats())
