"""Redis-locked periodic jobs: single runner, lock release, and fail-closed behaviour."""

from __future__ import annotations

import asyncio
from typing import Any

import fakeredis

from app.cache import keys
from worker.jobs.periodic import run_locked, was_skipped


async def test_run_locked_runs_job_and_releases_lock(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    async def job() -> int:
        assert await fake_redis.get(keys.job_lock("nightly")) is not None
        return 42

    assert await run_locked("nightly", job, lock_ttl=30, redis=fake_redis) == 42
    assert await fake_redis.get(keys.job_lock("nightly")) is None


async def test_only_one_instance_runs_at_a_time(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    runs = 0

    async def slow_job() -> None:
        nonlocal runs
        runs += 1
        started.set()
        await release.wait()

    first = asyncio.create_task(run_locked("nightly", slow_job, lock_ttl=30, redis=fake_redis))
    await started.wait()
    second = await run_locked("nightly", slow_job, lock_ttl=30, redis=fake_redis)
    assert was_skipped(second)
    release.set()
    await first
    assert runs == 1


async def test_lock_owned_by_another_instance_is_not_released(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    key = keys.job_lock("nightly")

    async def job() -> None:
        await fake_redis.set(key, "someone-else")  # simulate expiry + re-acquisition elsewhere

    await run_locked("nightly", job, lock_ttl=30, redis=fake_redis)
    assert await fake_redis.get(key) == "someone-else"


async def test_redis_outage_skips_job() -> None:
    class BrokenRedis:
        async def set(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("redis down")

    ran = False

    async def job() -> None:
        nonlocal ran
        ran = True

    result = await run_locked("nightly", job, lock_ttl=30, redis=BrokenRedis())  # type: ignore[arg-type]
    assert was_skipped(result)
    assert not ran
