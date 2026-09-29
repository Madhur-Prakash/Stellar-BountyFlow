"""Discovery jobs: rebuild the skill graph (every DISCOVERY_GRAPH_REFRESH_SECONDS) and send saved-search digests
that are due (checked every 5 minutes; each search is due at DISCOVERY_DIGEST_HOUR_UTC, daily or on Mondays)."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import session_scope
from worker.jobs.periodic import run_periodic

logger = get_logger(__name__)

GRAPH_JOB_NAME = "skill-graph"
GRAPH_LOCK_TTL_SECONDS = 300

DIGEST_JOB_NAME = "saved-search-digests"
DIGEST_INTERVAL_SECONDS = 300.0
DIGEST_LOCK_TTL_SECONDS = 240


async def run_graph_once() -> int:
    from app.modules.discovery.graph_store import refresh_graph

    async with session_scope() as session:
        graph = await refresh_graph(session)
    return len(graph.doc_counts)


async def run_digests_once() -> dict[str, int]:
    from app.modules.discovery.models import AlertFrequency
    from app.modules.discovery.saved_searches import run_digests

    results: dict[str, int] = {}
    # Separate transactions: a failure in one frequency must not hold back the other.
    for frequency in (AlertFrequency.DAILY, AlertFrequency.WEEKLY):
        try:
            async with session_scope() as session:
                results[frequency.value.lower()] = (await run_digests(session, frequency)).users
        except Exception:
            logger.exception("saved_search_digest_failed", frequency=frequency.value)
    return results


async def run_graph(stop: asyncio.Event) -> None:
    interval = float(get_settings().discovery_graph_refresh_seconds)
    await run_periodic(GRAPH_JOB_NAME, interval, run_graph_once, stop, lock_ttl=GRAPH_LOCK_TTL_SECONDS)


async def run_digests(stop: asyncio.Event) -> None:
    await run_periodic(
        DIGEST_JOB_NAME, DIGEST_INTERVAL_SECONDS, run_digests_once, stop, lock_ttl=DIGEST_LOCK_TTL_SECONDS
    )
