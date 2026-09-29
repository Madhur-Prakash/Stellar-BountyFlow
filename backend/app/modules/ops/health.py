"""Operational state the worker publishes for the API's ``/metrics`` and the ops endpoints.

The worker is a separate process, so what it knows (periodic job runs, Kafka consumer lag, the result of the
last chain-vs-database reconciliation audit) is written to Redis and read back when Prometheus scrapes the API.
Everything here is best effort: a Redis outage only makes the metrics stale, which the alert rules catch
(``BountyFlowWorkerJobStale``).
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.cache.redis import get_redis
from app.core.logging import get_logger

logger = get_logger(__name__)

JOBS_KEY = "bf:v1:ops:jobs"
KAFKA_LAG_KEY = "bf:v1:ops:kafka-lag"
RECONCILIATION_KEY = "bf:v1:ops:reconciliation"


async def record_job_run(name: str, started_at: float, duration: float, error: BaseException | None) -> None:
    """Called by the periodic job runner after every run it performed (skipped runs are not recorded)."""
    try:
        redis = get_redis()
        raw = await redis.hget(JOBS_KEY, name)
        state: dict[str, Any] = json.loads(raw) if raw else {"runs": 0, "failures": 0}
        state["runs"] = int(state.get("runs", 0)) + 1
        state["last_run"] = started_at
        state["last_duration"] = round(duration, 3)
        if error is None:
            state["last_success"] = started_at + duration
            state["consecutive_failures"] = 0
        else:
            state["failures"] = int(state.get("failures", 0)) + 1
            state["consecutive_failures"] = int(state.get("consecutive_failures", 0)) + 1
            state["last_error"] = f"{type(error).__name__}: {error}"[:300]
            state["last_error_at"] = time.time()
        await redis.hset(JOBS_KEY, name, json.dumps(state))
    except Exception as exc:
        logger.debug("job_health_unavailable", job=name, error=str(exc))


async def job_health() -> dict[str, dict[str, Any]]:
    try:
        raw = await get_redis().hgetall(JOBS_KEY)
    except Exception:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        try:
            out[str(name)] = json.loads(value)
        except json.JSONDecodeError:
            continue
    return out


async def record_consumer_lag(consumer: str, partitions: dict[str, int]) -> None:
    try:
        value = json.dumps({"total": sum(partitions.values()), "partitions": partitions, "at": time.time()})
        await get_redis().hset(KAFKA_LAG_KEY, consumer, value)
    except Exception as exc:
        logger.debug("consumer_lag_unrecorded", consumer=consumer, error=str(exc))


async def consumer_lag() -> dict[str, dict[str, Any]]:
    try:
        raw = await get_redis().hgetall(KAFKA_LAG_KEY)
    except Exception:
        return {}
    return {str(name): json.loads(value) for name, value in raw.items()}


async def save_reconciliation(result: dict[str, Any]) -> None:
    try:
        await get_redis().set(RECONCILIATION_KEY, json.dumps(result, default=str))
    except Exception as exc:
        logger.warning("reconciliation_result_unrecorded", error=str(exc))


async def reconciliation() -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(RECONCILIATION_KEY)
    except Exception:
        return None
    return json.loads(raw) if raw else None


async def worker_heartbeats() -> dict[str, float]:
    """Seconds since each worker's last heartbeat (the heartbeat key expires after 30 s without one)."""
    try:
        redis = get_redis()
        keys = [k async for k in redis.scan_iter(match="bf:v1:worker:heartbeat:*", count=100)]
        out: dict[str, float] = {}
        for key in keys:
            raw = await redis.get(key)
            if not raw:
                continue
            at = json.loads(raw).get("at")
            if at:
                from datetime import datetime

                out[key.rsplit(":", 1)[-1]] = max(0.0, time.time() - datetime.fromisoformat(at).timestamp())
        return out
    except Exception:
        return {}
