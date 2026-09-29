"""Feedback use cases: receive a note, read the queue, mark a note handled.

* Anyone may send one, signed in or not. A signed-in sender is recorded by ``user_id`` and their account's
  address is used for any reply, so the submitted ``email`` is ignored; a signed-out sender may leave one.
* Nothing is emailed on arrival. One person reads this queue, so a mail per submission would be a way to flood
  their inbox from an anonymous form. Storing the row is the whole delivery.
* Staff read and triage the queue behind ``feedback:review``. Marking a note handled (or putting it back) is
  written to the append-only audit log.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, and_, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound
from app.core.schemas import Page, PageParams, UserSummary
from app.core.security import utcnow
from app.modules.admin import audit
from app.modules.feedback.models import Feedback, FeedbackKind, FeedbackStatus
from app.modules.feedback.schemas import (
    FeedbackCreate,
    FeedbackOut,
    FeedbackPage,
)
from app.modules.users.models import User

USER_AGENT_MAX = 400


def _summary(user: User | None) -> UserSummary | None:
    if user is None:
        return None
    return UserSummary(
        id=user.id, username=user.username, display_name=user.display_name, avatar_url=user.avatar_url
    )


def feedback_out(row: Feedback) -> FeedbackOut:
    return FeedbackOut(
        id=row.id,
        kind=row.kind,
        status=row.status,
        message=row.message,
        sender=_summary(row.sender),
        email=row.email,
        path=row.path,
        viewport_width=row.viewport_width,
        viewport_height=row.viewport_height,
        user_agent=row.user_agent,
        created_at=row.created_at,
        handled_at=row.handled_at,
        handled_by=_summary(row.handled_by),
        handled_note=row.handled_note,
    )


# --- Receiving ---------------------------------------------------------------------------------


async def submit(
    session: AsyncSession, sender: User | None, data: FeedbackCreate, user_agent: str | None
) -> Feedback:
    """Store one note. Single transaction, single commit; no chain or mail I/O."""
    row = Feedback(
        user_id=sender.id if sender else None,
        # A signed-in sender is reachable through their account, so the form's address is not kept beside it.
        email=None if sender else (str(data.email) if data.email else None),
        kind=data.kind,
        status=FeedbackStatus.NEW,
        message=data.message,
        path=data.path,
        viewport_width=data.viewport_width,
        viewport_height=data.viewport_height,
        user_agent=user_agent[:USER_AGENT_MAX] if user_agent else None,
    )
    session.add(row)
    await session.commit()
    return row


# --- Queue -------------------------------------------------------------------------------------


async def list_feedback(
    session: AsyncSession,
    params: PageParams,
    *,
    kind: FeedbackKind | None = None,
    status: FeedbackStatus | None = None,
) -> FeedbackPage:
    conditions: list[ColumnElement[bool]] = []
    if kind is not None:
        conditions.append(Feedback.kind == kind)
    if status is not None:
        conditions.append(Feedback.status == status)
    # One pass over the table for both numbers: the filtered total and everything still waiting.
    totals = (
        await session.execute(
            select(
                func.count(Feedback.id).filter(and_(*conditions) if conditions else true()),
                func.count(Feedback.id).filter(Feedback.status == FeedbackStatus.NEW),
            )
        )
    ).one()
    rows = (
        (
            await session.scalars(
                select(Feedback)
                .where(*conditions)
                # Both people on a row are loaded with it (lazy="joined"), so a page is one query.
                .order_by(Feedback.created_at.desc(), Feedback.id.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    items = [feedback_out(r) for r in rows]
    page = Page[FeedbackOut].build(items, int(totals[0] or 0), params)
    return FeedbackPage(**page.model_dump(exclude={"items"}), items=items, new_count=int(totals[1] or 0))


async def set_handled(
    session: AsyncSession, actor: User, feedback_id: uuid.UUID, handled: bool, note: str | None
) -> FeedbackOut:
    row = await session.scalar(
        select(Feedback).where(Feedback.id == feedback_id).with_for_update(of=Feedback)
    )
    if row is None:
        raise NotFound("Feedback not found.")
    now = utcnow()
    row.status = FeedbackStatus.HANDLED if handled else FeedbackStatus.NEW
    row.handled_at = now if handled else None
    row.handled_by_id = actor.id if handled else None
    row.handled_note = note if handled else None
    audit.record(
        session,
        actor_id=actor.id,
        action="feedback.handled" if handled else "feedback.reopened",
        entity_type="feedback",
        entity_id=row.id,
        metadata={"kind": row.kind.value},
        is_public=False,
    )
    await session.commit()
    await session.refresh(row)
    return feedback_out(row)
