"""Skill graph persistence: built from bounties and profiles, stored in Postgres, cached in Redis.

The worker rebuilds the graph on a schedule (``refresh_graph``) and writes it to ``skill_nodes`` / ``skill_edges``
and to Redis. Readers (``load_graph``) take the Redis copy, fall back to the tables when Redis is empty or down,
and only build it in memory when it has never been computed (a fresh install before the worker's first run).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import keys
from app.cache.redis import cache_get_json, cache_set_json
from app.core.logging import get_logger
from app.core.security import utcnow
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties.models import Bounty, BountySkill, BountyTag
from app.modules.discovery.graph import Edge, SkillGraph, build_graph
from app.modules.discovery.models import SkillEdge, SkillNode
from app.modules.users.models import User, UserSkill

logger = get_logger(__name__)

GRAPH_CACHE_KEY = f"{keys.PREFIX}:discovery:skill-graph"
GRAPH_CACHE_TTL = 6 * 3600
# Serialises concurrent rebuilds (two worker replicas, or a job overlapping a manual run).
GRAPH_LOCK_KEY = 7_265_110_392_184_409
_INSERT_BATCH = 1000


async def collect_documents(session: AsyncSession) -> tuple[list[list[str]], list[str]]:
    """Every skill set that says which skills belong together: each listed bounty's required skills and tags, and
    each active user's profile skills. Also returns the raw required-skill names of those bounties."""
    docs: dict[object, list[str]] = defaultdict(list)
    required_names: list[str] = []
    listed = select(Bounty.id).where(bounty_repo.public_filter())
    for bounty_id, name in (
        await session.execute(
            select(BountySkill.bounty_id, BountySkill.skill_name).where(BountySkill.bounty_id.in_(listed))
        )
    ).all():
        docs[("bounty", bounty_id)].append(name)
        required_names.append(name)
    for bounty_id, tag in (
        await session.execute(
            select(BountyTag.bounty_id, BountyTag.tag).where(BountyTag.bounty_id.in_(listed))
        )
    ).all():
        docs[("bounty", bounty_id)].append(tag)
    for user_id, name in (
        await session.execute(
            select(UserSkill.user_id, UserSkill.skill_name)
            .join(User, User.id == UserSkill.user_id)
            .where(User.is_active.is_(True))
        )
    ).all():
        docs[("user", user_id)].append(name)
    return list(docs.values()), required_names


async def compute_graph(session: AsyncSession, now: datetime | None = None) -> SkillGraph:
    documents, required_names = await collect_documents(session)
    return build_graph(documents, bounty_skill_names=required_names, computed_at=now or utcnow())


async def persist_graph(session: AsyncSession, graph: SkillGraph) -> None:
    """Replaces the stored graph in the caller's transaction."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": GRAPH_LOCK_KEY})
    await session.execute(delete(SkillEdge))
    await session.execute(delete(SkillNode))
    computed_at = graph.computed_at or utcnow()
    nodes = [
        {
            "skill": skill,
            "doc_count": count,
            "bounty_forms": list(graph.bounty_forms.get(skill, ()))[:10],
            "computed_at": computed_at,
        }
        for skill, count in graph.doc_counts.items()
    ]
    edges = [
        {
            "skill": skill,
            "related": e.related,
            "co_count": e.co_count,
            "weight": e.weight,
            "computed_at": computed_at,
        }
        for skill, neighbours in graph.neighbors.items()
        for e in neighbours
    ]
    for table, rows in ((SkillNode, nodes), (SkillEdge, edges)):
        for start in range(0, len(rows), _INSERT_BATCH):
            await session.execute(insert(table).values(rows[start : start + _INSERT_BATCH]))


async def cache_graph(graph: SkillGraph) -> None:
    await cache_set_json(GRAPH_CACHE_KEY, graph.to_json(), GRAPH_CACHE_TTL)


async def refresh_graph(session: AsyncSession) -> SkillGraph:
    """Worker job: rebuild from source tables, store, and cache."""
    graph = await compute_graph(session)
    await persist_graph(session, graph)
    await session.commit()
    await cache_graph(graph)
    logger.info(
        "skill_graph_refreshed",
        documents=graph.documents,
        skills=len(graph.doc_counts),
        edges=sum(len(v) for v in graph.neighbors.values()),
    )
    return graph


async def _from_tables(session: AsyncSession) -> SkillGraph | None:
    nodes = (await session.scalars(select(SkillNode))).all()
    if not nodes:
        return None
    neighbours: dict[str, list[Edge]] = defaultdict(list)
    for row in (await session.scalars(select(SkillEdge))).all():
        neighbours[row.skill].append(Edge(row.related, row.weight, row.co_count))
    return SkillGraph(
        documents=0,
        doc_counts={n.skill: n.doc_count for n in nodes},
        neighbors={
            s: tuple(sorted(edges, key=lambda e: (-e.weight, -e.co_count, e.related)))
            for s, edges in neighbours.items()
        },
        bounty_forms={n.skill: tuple(n.bounty_forms) for n in nodes if n.bounty_forms},
        computed_at=max(n.computed_at for n in nodes),
    )


async def load_graph(session: AsyncSession) -> SkillGraph:
    cached = await cache_get_json(GRAPH_CACHE_KEY)
    if cached is not None:
        try:
            return SkillGraph.from_json(cached)
        except (TypeError, ValueError, KeyError):
            logger.warning("skill_graph_cache_unreadable")
    graph = await _from_tables(session)
    if graph is None:
        graph = await compute_graph(session)
    await cache_graph(graph)
    return graph
