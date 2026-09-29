"""Database access for bounty Q&A."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Exists, Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.qa.models import BountyQAPost, BountyQAVote
from app.modules.qa.schemas import QASort


def _visible_reply_exists() -> Exists:
    reply = aliased(BountyQAPost)
    return exists().where(reply.parent_id == BountyQAPost.id, reply.deleted_at.is_(None))


def listed_questions(bounty_id: uuid.UUID) -> Select[BountyQAPost]:
    """Questions shown on the bounty: every question except deleted ones nobody replied to."""
    return select(BountyQAPost).where(
        BountyQAPost.bounty_id == bounty_id,
        BountyQAPost.parent_id.is_(None),
        or_(BountyQAPost.deleted_at.is_(None), _visible_reply_exists()),
    )


def ordered(stmt: Select[BountyQAPost], sort: QASort) -> Select[BountyQAPost]:
    if sort == QASort.HELPFUL:
        return stmt.order_by(
            BountyQAPost.is_pinned.desc(), BountyQAPost.upvotes_count.desc(), BountyQAPost.created_at.desc()
        )
    return stmt.order_by(BountyQAPost.is_pinned.desc(), BountyQAPost.created_at.desc(), BountyQAPost.id)


async def replies_for(
    session: AsyncSession, question_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[BountyQAPost]]:
    if not question_ids:
        return {}
    rows = await session.scalars(
        select(BountyQAPost)
        .where(BountyQAPost.parent_id.in_(question_ids), BountyQAPost.deleted_at.is_(None))
        .order_by(BountyQAPost.created_at, BountyQAPost.id)
    )
    grouped: dict[uuid.UUID, list[BountyQAPost]] = {}
    for row in rows.unique().all():
        if row.parent_id is not None:
            grouped.setdefault(row.parent_id, []).append(row)
    return grouped


async def voted_ids(
    session: AsyncSession, user_id: uuid.UUID, post_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    if not post_ids:
        return set()
    rows = await session.scalars(
        select(BountyQAVote.post_id).where(
            BountyQAVote.user_id == user_id, BountyQAVote.post_id.in_(post_ids)
        )
    )
    return set(rows.all())


async def question_counts(session: AsyncSession, bounty_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Visible questions per bounty (not deleted, not hidden), for bounty cards and detail."""
    if not bounty_ids:
        return {}
    rows = await session.execute(
        select(BountyQAPost.bounty_id, func.count(BountyQAPost.id))
        .where(
            BountyQAPost.bounty_id.in_(bounty_ids),
            BountyQAPost.parent_id.is_(None),
            BountyQAPost.deleted_at.is_(None),
            BountyQAPost.hidden_at.is_(None),
        )
        .group_by(BountyQAPost.bounty_id)
    )
    return {bounty_id: int(count) for bounty_id, count in rows.all()}


async def thread_participants(
    session: AsyncSession, question: BountyQAPost, *, exclude: uuid.UUID, limit: int = 50
) -> list[uuid.UUID]:
    """The asker and everyone who replied visibly in the thread, except ``exclude`` (the actor)."""
    rows = await session.scalars(
        select(BountyQAPost.author_id)
        .where(
            BountyQAPost.parent_id == question.id,
            and_(BountyQAPost.deleted_at.is_(None), BountyQAPost.hidden_at.is_(None)),
            BountyQAPost.author_id != exclude,
        )
        .distinct()
        .limit(limit)
    )
    ids = [question.author_id] if question.author_id != exclude else []
    ids += [a for a in rows.all() if a not in ids]
    return ids[:limit]


async def pinned_count(session: AsyncSession, bounty_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count(BountyQAPost.id)).where(
                BountyQAPost.bounty_id == bounty_id, BountyQAPost.parent_id.is_(None), BountyQAPost.is_pinned
            )
        )
        or 0
    )
