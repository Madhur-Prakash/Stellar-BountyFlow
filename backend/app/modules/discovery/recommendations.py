"""Recommendations for the signed-in user, and related skills, on top of the skill graph.

Candidates are the bounties the marketplace would list (optionally narrowed by its filters) that still accept
applications, that the user did not post or apply to, and that carry at least one skill the user's seeds reach in
the graph. ``ranking.rank`` orders them. The ranked list is cached briefly per user; the key includes the
marketplace cache generation (so any bounty change invalidates it), the graph version and the user's seeds.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import keys
from app.cache.invalidation import current_generation
from app.cache.redis import cache_get_json, cache_set_json
from app.core.schemas import Page, PageParams
from app.core.security import utcnow
from app.modules.applications.models import AssignmentStatus, BountyApplication, BountyAssignment
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties import state_machine as sm
from app.modules.bounties.models import Bounty, BountyBookmark, BountySkill, BountyTag
from app.modules.bounties.schemas import MarketplaceFilters
from app.modules.discovery import ranking
from app.modules.discovery.graph import SkillGraph, related_skills
from app.modules.discovery.graph_store import load_graph
from app.modules.discovery.saved_searches import match_clause
from app.modules.discovery.schemas import (
    Recommendation,
    RecommendationPage,
    RecommendationReason,
    RelatedMatchOut,
    RelatedSkill,
    RelatedSkills,
)
from app.modules.discovery.skills import match_keys, normalize_all
from app.modules.users.models import User

MAX_CANDIDATES = 500
MAX_SIGNAL_BOUNTIES = 200
CACHE_TTL = 60
SEED_SKILLS_SHOWN = 8


# --- Signals -------------------------------------------------------------------------------------


async def _skill_sets(
    session: AsyncSession, bounty_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ranking.SkillSet]:
    if not bounty_ids:
        return {}
    required: dict[uuid.UUID, list[str]] = defaultdict(list)
    tags: dict[uuid.UUID, list[str]] = defaultdict(list)
    for bounty_id, name in (
        await session.execute(
            select(BountySkill.bounty_id, BountySkill.skill_name).where(BountySkill.bounty_id.in_(bounty_ids))
        )
    ).all():
        required[bounty_id].append(name)
    for bounty_id, tag in (
        await session.execute(
            select(BountyTag.bounty_id, BountyTag.tag).where(BountyTag.bounty_id.in_(bounty_ids))
        )
    ).all():
        tags[bounty_id].append(tag)
    return {b: ranking.SkillSet(required=required.get(b, []), tags=tags.get(b, [])) for b in bounty_ids}


async def user_signals(session: AsyncSession, user: User) -> ranking.UserSignals:
    completed = (
        await session.scalars(
            select(BountyAssignment.bounty_id)
            .where(
                BountyAssignment.contributor_id == user.id,
                BountyAssignment.status == AssignmentStatus.COMPLETED,
            )
            .limit(MAX_SIGNAL_BOUNTIES)
        )
    ).all()
    applied = (
        await session.scalars(
            select(BountyApplication.bounty_id)
            .where(BountyApplication.contributor_id == user.id)
            .order_by(BountyApplication.created_at.desc())
            .limit(MAX_SIGNAL_BOUNTIES)
        )
    ).all()
    bookmarked = (
        await session.scalars(
            select(BountyBookmark.bounty_id)
            .where(BountyBookmark.user_id == user.id)
            .order_by(BountyBookmark.created_at.desc())
            .limit(MAX_SIGNAL_BOUNTIES)
        )
    ).all()
    sets = await _skill_sets(session, list({*completed, *applied, *bookmarked}))
    return ranking.UserSignals(
        profile=user.skill_names,
        completed=[sets[b] for b in completed if b in sets],
        applied=[sets[b] for b in applied if b in sets],
        bookmarked=[sets[b] for b in bookmarked if b in sets],
    )


# --- Candidates ------------------------------------------------------------------------------------


def _normalised_name(column: Any) -> Any:
    """SQL twin of the separator-insensitive key in ``skills``: lower case, runs of space/_/- as one space."""
    return func.regexp_replace(func.lower(func.trim(column)), r"[\s_\-]+", " ", "g")


async def _candidates(
    session: AsyncSession, user: User, filters: MarketplaceFilters, reachable: Iterable[str], now: datetime
) -> list[Bounty]:
    names = match_keys(reachable)
    if not names:
        return []
    applied = exists().where(
        BountyApplication.bounty_id == Bounty.id, BountyApplication.contributor_id == user.id
    )
    has_skill = or_(
        exists().where(
            BountySkill.bounty_id == Bounty.id, _normalised_name(BountySkill.skill_name).in_(names)
        ),
        exists().where(BountyTag.bounty_id == Bounty.id, _normalised_name(BountyTag.tag).in_(names)),
    )
    stmt = (
        select(Bounty)
        .where(
            match_clause(filters),
            Bounty.status.in_(sm.ACCEPTING_APPLICATIONS),
            or_(Bounty.application_deadline.is_(None), Bounty.application_deadline > now),
            Bounty.requester_id != user.id,
            ~applied,
            has_skill,
        )
        .order_by(func.coalesce(Bounty.published_at, Bounty.created_at).desc())
        .limit(MAX_CANDIDATES)
    )
    return list((await session.scalars(stmt)).unique().all())


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _cache_key(
    user: User, generation: int, graph: SkillGraph, filters: MarketplaceFilters, seeds: Any
) -> str:
    version = graph.computed_at.isoformat() if graph.computed_at else "none"
    part = _digest({"f": filters.cache_key_params(), "s": seeds, "g": version})
    return f"{keys.PREFIX}:discovery:recs:{user.id}:g{generation}:{part}"


async def _ranked(
    session: AsyncSession, user: User, filters: MarketplaceFilters, seeds: dict[str, float], graph: SkillGraph
) -> list[dict[str, Any]]:
    """Ranked entries ``{id, score, matched, related}``, cached for a minute."""
    generation = await current_generation()
    key = _cache_key(user, generation, graph, filters, sorted(seeds.items()))
    cached = await cache_get_json(key) if generation >= 0 else None
    if isinstance(cached, list):
        return cached
    now = utcnow()
    reach = ranking.reach(seeds, graph)
    bounties = await _candidates(session, user, filters, reach.skills, now)
    ids = [b.id for b in bounties]
    filled = await bounty_repo.positions_filled(session, ids)
    escrows = await bounty_repo.escrows(session, ids)
    candidates = [
        ranking.Candidate(
            bounty_id=b.id,
            skills=ranking.SkillSet(required=b.skill_names, tags=b.tag_names),
            reward=b.reward_amount,
            # The asset identifier, never the display code: rewards are only ever compared within one asset, and
            # two different issuers can both call their asset "USDC".
            asset=b.reward_asset_identifier or "native",
            deadline=b.application_deadline or b.completion_deadline,
            funding_status=bounty_service.funding_status(b, escrows.get(b.id)).value,
            listed_at=b.published_at or b.created_at,
        )
        for b in bounties
        if filled.get(b.id, 0) < b.positions_available
    ]
    entries = [
        {
            "id": str(r.bounty_id),
            "score": r.score,
            "matched": list(r.proximity.matched),
            "related": [[m.skill, m.via] for m in r.proximity.related],
        }
        for r in ranking.rank(candidates, reach, now)
    ]
    if generation >= 0:
        await cache_set_json(key, entries, CACHE_TTL)
    return entries


def _reason(entry: dict[str, Any]) -> RecommendationReason:
    return RecommendationReason(
        matched_skills=list(entry.get("matched", [])),
        related_skills=[RelatedMatchOut(skill=s, via=v) for s, v in entry.get("related", [])],
    )


async def recommend(
    session: AsyncSession, user: User, filters: MarketplaceFilters | None, params: PageParams
) -> RecommendationPage:
    signals = await user_signals(session, user)
    seeds = ranking.seed_weights(signals)
    has_profile = bool(normalize_all(signals.profile))
    shown = [s for s, _ in sorted(seeds.items(), key=lambda kv: (-kv[1], kv[0]))[:SEED_SKILLS_SHOWN]]
    entries: list[dict[str, Any]] = []
    items: list[Recommendation] = []
    if seeds:
        graph = await load_graph(session)
        entries = await _ranked(session, user, filters or MarketplaceFilters(), seeds, graph)
        window = entries[params.offset : params.offset + params.page_size]
        ids = [uuid.UUID(e["id"]) for e in window]
        found = (await session.scalars(select(Bounty).where(Bounty.id.in_(ids)))).unique().all()
        rows = {b.id: b for b in found}
        ordered = [rows[i] for i in ids if i in rows]
        summaries = {s.id: s for s in await bounty_service.summaries(session, ordered, user)}
        items = [
            Recommendation(bounty=summaries[uuid.UUID(e["id"])], score=e["score"], reason=_reason(e))
            for e in window
            if uuid.UUID(e["id"]) in summaries
        ]
    page = Page[Recommendation].build(items, len(entries), params)
    return RecommendationPage(
        items=page.items,
        total=page.total,
        page=page.page,
        page_size=page.page_size,
        pages=page.pages,
        seed_skills=shown,
        has_profile_skills=has_profile,
    )


async def related(session: AsyncSession, skills: Sequence[str], limit: int) -> RelatedSkills:
    graph = await load_graph(session)
    inputs = normalize_all(skills)
    return RelatedSkills(
        skills=inputs,
        related=[
            RelatedSkill(
                skill=r.skill,
                weight=round(r.weight, 4),
                via=list(r.via),
                marketplace_skills=list(graph.bounty_forms.get(r.skill, ()))[:3],
            )
            for r in related_skills(graph, inputs, limit)
        ],
        computed_at=graph.computed_at,
    )
