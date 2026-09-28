"""Periodic job runner with a Redis lock, so only one worker instance runs a given job at a time."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import WatchError

from app.cache import keys
from app.cache.redis import get_redis
from app.core.logging import get_logger
from worker.retry import interruptible_sleep

logger = get_logger(__name__)

_NOT_ACQUIRED = object()


async def _release(redis: Redis, key: str, token: str) -> None:
    """Delete the lock only if we still own it (compare-and-delete with WATCH/MULTI)."""
    try:
        async with redis.pipeline(transaction=True) as pipe:
            await pipe.watch(key)
            if await pipe.get(key) == token:
                pipe.multi()
                pipe.delete(key)
                await pipe.execute()
            else:
                await pipe.unwatch()
    except WatchError:
        pass  # the lock changed hands (expired and re-acquired); nothing to release
    except Exception as exc:
        logger.warning("job_lock_release_failed", key=key, error=str(exc))


async def run_locked(
    name: str,
    job: Callable[[], Awaitable[Any]],
    *,
    lock_ttl: int,
    redis: Redis | None = None,
) -> Any:
    """Run ``job`` if the lock for ``name`` can be acquired. Returns the job result, or ``_NOT_ACQUIRED``.
    Fails closed: if Redis is unavailable the job is skipped rather than run unguarded. The job is bounded by
    a timeout shorter than the lock TTL so the lock cannot expire while it runs."""
    redis = redis or get_redis()
    key = keys.job_lock(name)
    token = uuid.uuid4().hex
    try:
        acquired = await redis.set(key, token, nx=True, ex=lock_ttl)
    except Exception as exc:
        logger.warning("job_lock_unavailable", job=name, error=str(exc))
        return _NOT_ACQUIRED
    if not acquired:
        logger.debug("job_skipped_locked", job=name)
        return _NOT_ACQUIRED
    try:
        async with asyncio.timeout(max(1, lock_ttl - 5)):
            return await job()
    finally:
        await _release(redis, key, token)


def was_skipped(result: Any) -> bool:
    return result is _NOT_ACQUIRED


async def run_periodic(
    name: str,
    interval: float,
    job: Callable[[], Awaitable[Any]],
    stop: asyncio.Event,
    *,
    lock_ttl: int,
) -> None:
    logger.info("periodic_job_started", job=name, interval=interval)
    while not stop.is_set():
        started = time.monotonic()
        try:
            await run_locked(name, job, lock_ttl=lock_ttl)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic_job_failed", job=name)
        elapsed = time.monotonic() - started
        await interruptible_sleep(max(0.0, interval - elapsed), stop)
    logger.info("periodic_job_stopped", job=name)
