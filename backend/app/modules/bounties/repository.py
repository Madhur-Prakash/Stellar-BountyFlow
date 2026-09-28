"""Database access for bounties, including indexed marketplace search and batched related-data loading."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.bounties.models import (
    Bounty,
    BountyBookmark,
    BountySkill,
    BountyStatus,
    BountyTag,
    BountyViewDaily,
    Visibility,
)
from app.modules.bounties.schemas import MarketplaceFilters, SortOption
from app.modules.bounties.state_machine import MARKETPLACE_DEFAULT
from app.modules.payments.models import BountyEscrow, EscrowState

LIVE_ASSIGNMENT = (AssignmentStatus.ACTIVE, AssignmentStatus.COMPLETED)


async def get(session: AsyncSession, bounty_id: uuid.UUID, *, for_update: bool = False) -> Bounty | None:
    stmt = select(Bounty).where(Bounty.id == bounty_id)
    if for_update:
        # populate_existing: the bounty may already sit in the identity map (e.g. loaded through a transaction's
        # joined relationship before a slow network call). Without it the locked read would hand back that stale
        # copy, and the next commit would fail the optimistic version check (StaleDataError).
        stmt = stmt.with_for_update(of=Bounty).execution_options(populate_existing=True)
    return await session.scalar(stmt)


async def get_by_id_or_slug(session: AsyncSession, ref: str) -> Bounty | None:
    try:
        return await get(session, uuid.UUID(ref))
    except ValueError:
        return await session.scalar(select(Bounty).where(Bounty.slug == ref.lower()))


async def slug_exists(session: AsyncSession, slug: str) -> bool:
    return (await session.scalar(select(Bounty.id).where(Bounty.slug == slug))) is not None


def set_tags(bounty: Bounty, tags: list[str]) -> None:
    existing = {t.tag: t for t in bounty.tags}
    bounty.tags = [existing.get(t) or BountyTag(tag=t) for t in tags]


def set_skills(bounty: Bounty, skills: list[str]) -> None:
    existing = {s.skill_name: s for s in bounty.skills}
    bounty.skills = [existing.get(s) or BountySkill(skill_name=s) for s in skills]


def _views_7d_subquery() -> Any:
    since = datetime.now(UTC).date() - timedelta(days=7)
    return (
        select(BountyViewDaily.bounty_id, func.sum(BountyViewDaily.views).label("views"))
        .where(BountyViewDaily.day >= since)
        .group_by(BountyViewDaily.bounty_id)
        .subquery()
    )


def contains_pattern(term: str) -> str:
    """ILIKE pattern matching ``term`` literally; use it with a backslash ``escape`` character.

    Security: percent, underscore and backslash in user input are escaped so they cannot act as wildcards
    (match-everything or pathological patterns)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def public_filter() -> Any:
    return and_(
        Bounty.visibility == Visibility.PUBLIC,
        Bounty.is_hidden.is_(False),
        Bounty.status != BountyStatus.DRAFT,
    )


def marketplace_query(filters: MarketplaceFilters) -> tuple[Select[Bounty], Select[int]]:
    conditions: list[Any] = [public_filter()]
    statuses = filters.status or list(MARKETPLACE_DEFAULT)
    conditions.append(Bounty.status.in_(statuses))
    ts_query = None
    if filters.q and filters.q.strip():
        ts_query = func.websearch_to_tsquery("english", filters.q.strip())
        pattern = contains_pattern(filters.q.strip())
        conditions.append(
            or_(Bounty.search_vector.op("@@")(ts_query), Bounty.title.ilike(pattern, escape="\\"))
        )
    if filters.category:
        conditions.append(Bounty.category.in_(filters.category))
    if filters.difficulty:
        conditions.append(Bounty.difficulty.in_(filters.difficulty))
    if filters.skills:
        conditions.append(
            exists().where(BountySkill.bounty_id == Bounty.id, BountySkill.skill_name.in_(filters.skills))
        )
    if filters.tags:
        conditions.append(exists().where(BountyTag.bounty_id == Bounty.id, BountyTag.tag.in_(filters.tags)))
    if filters.min_reward is not None:
        conditions.append(Bounty.reward_amount >= filters.min_reward)
    if filters.max_reward is not None:
        conditions.append(Bounty.reward_amount <= filters.max_reward)
    deadline = func.coalesce(Bounty.application_deadline, Bounty.completion_deadline)
    if filters.deadline_before is not None:
        conditions.append(deadline <= filters.deadline_before)
    if filters.deadline_after is not None:
        conditions.append(deadline >= filters.deadline_after)
    if filters.funded_only:
        conditions.append(
            exists().where(
                BountyEscrow.bounty_id == Bounty.id,
                BountyEscrow.state.in_([EscrowState.FUNDED, EscrowState.COMPLETED]),
            )
        )

    stmt = select(Bounty).where(*conditions)
    count = select(func.count(Bounty.id)).where(*conditions)

    sort = filters.sort or (SortOption.RELEVANCE if ts_query is not None else SortOption.NEWEST)
    newest = func.coalesce(Bounty.published_at, Bounty.created_at).desc()
    if sort == SortOption.RELEVANCE and ts_query is not None:
        stmt = stmt.order_by(func.ts_rank_cd(Bounty.search_vector, ts_query).desc(), newest)
    elif sort == SortOption.DEADLINE:
        stmt = stmt.order_by(deadline.asc().nulls_last(), newest)
    elif sort == SortOption.REWARD_HIGH:
        stmt = stmt.order_by(Bounty.reward_amount.desc(), newest)
    elif sort == SortOption.REWARD_LOW:
        stmt = stmt.order_by(Bounty.reward_amount.asc(), newest)
    elif sort == SortOption.POPULAR:
        views = _views_7d_subquery()
        score = Bounty.applications_count * 3 + Bounty.bookmarks_count * 2 + func.coalesce(views.c.views, 0)
        stmt = stmt.outerjoin(views, views.c.bounty_id == Bounty.id).order_by(score.desc(), newest)
    else:
        stmt = stmt.order_by(newest)
    return stmt, count


async def positions_filled(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await session.execute(
        select(BountyAssignment.bounty_id, func.count(BountyAssignment.id))
        .where(BountyAssignment.bounty_id.in_(ids), BountyAssignment.status.in_(LIVE_ASSIGNMENT))
        .group_by(BountyAssignment.bounty_id)
    )
    return {bid: count for bid, count in rows.all()}


async def escrows(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, BountyEscrow]:
    if not ids:
        return {}
    rows = await session.scalars(select(BountyEscrow).where(BountyEscrow.bounty_id.in_(ids)))
    return {e.bounty_id: e for e in rows.all()}


async def get_escrow(
    session: AsyncSession, bounty_id: uuid.UUID, *, for_update: bool = False
) -> BountyEscrow | None:
    stmt = select(BountyEscrow).where(BountyEscrow.bounty_id == bounty_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return await session.scalar(stmt)


async def bookmarked_ids(
    session: AsyncSession, user_id: uuid.UUID, ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    if not ids:
        return set()
    rows = await session.scalars(
        select(BountyBookmark.bounty_id).where(
            BountyBookmark.user_id == user_id, BountyBookmark.bounty_id.in_(ids)
        )
    )
    return set(rows.all())


async def add_bookmark(session: AsyncSession, user_id: uuid.UUID, bounty_id: uuid.UUID) -> bool:
    result = await session.execute(
        insert(BountyBookmark)
        .values(id=uuid.uuid4(), user_id=user_id, bounty_id=bounty_id)
        .on_conflict_do_nothing(index_elements=["user_id", "bounty_id"])
        .returning(BountyBookmark.id)
    )
    return result.scalar_one_or_none() is not None


async def record_view(session: AsyncSession, bounty_id: uuid.UUID, day: date) -> None:
    await session.execute(
        insert(BountyViewDaily)
        .values(bounty_id=bounty_id, day=day, views=1)
        .on_conflict_do_update(index_elements=["bounty_id", "day"], set_={"views": BountyViewDaily.views + 1})
    )
