"""Bounty Q&A use cases: ask, reply (one level), edit, delete, upvote, accept, pin, report, and moderation.

* Anyone who can see a bounty can read its questions. Posting needs a signed-in, active account with a verified
  email, and closes when the bounty is completed, cancelled or expired.
* The requester's posts are marked as theirs. The requester accepts one reply per question and pins up to
  ``MAX_PINNED`` questions.
* Authors edit (marked "edited") and delete (soft: the body is cleared, replies keep their thread) their own
  posts. Moderators hide and unhide posts with a reason; hiding a post actions its open reports. Every
  moderation step is written to the audit log.
* Events on the outbox drive notifications: the requester hears about new questions; the asker and the other
  people in a thread hear about replies and accepted answers.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.invalidation import invalidate_bounty
from app.core.exceptions import Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.rate_limit import hit
from app.core.rbac import Permission, has_permission
from app.core.schemas import Page, PageParams
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.admin.models import ReportStatus, ReportTarget, UserReport
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.qa import repository as repo
from app.modules.qa.models import BountyQAPost, BountyQAVote
from app.modules.qa.schemas import (
    QUESTION_MIN,
    ModeratedPostOut,
    PostOut,
    QASort,
    QuestionPage,
    ThreadOut,
    VoteOut,
)
from app.modules.users.models import User

MAX_PINNED = 3
CLOSED_STATUSES = frozenset({BountyStatus.COMPLETED, BountyStatus.CANCELLED, BountyStatus.EXPIRED})
OPEN_REPORT_STATUSES = (ReportStatus.OPEN, ReportStatus.REVIEWING)
EXCERPT_LENGTH = 280


def question_link(bounty: Bounty, question_id: uuid.UUID) -> str:
    return f"/bounties/{bounty.slug}#q-{question_id}"


# --- Serialization -----------------------------------------------------------------------------------


def _is_moderator(user: User | None) -> bool:
    return has_permission(user, Permission.BOUNTY_MODERATE)


def post_out(post: BountyQAPost, bounty: Bounty, viewer: User | None, voted: set[uuid.UUID]) -> PostOut:
    deleted = post.deleted_at is not None
    hidden = post.hidden_at is not None
    mine = viewer is not None and post.author_id == viewer.id
    privileged = mine or _is_moderator(viewer)
    body: str | None = post.body
    if deleted or (hidden and not privileged):
        body = None
    return PostOut(
        id=post.id,
        question_id=post.parent_id or post.id,
        parent_id=post.parent_id,
        author=None if deleted else bounty_service.user_summary(post.author),
        body=body,
        is_requester=post.author_id == bounty.requester_id,
        is_mine=mine and not deleted,
        is_pinned=post.is_pinned,
        is_accepted=post.is_accepted,
        upvotes=post.upvotes_count,
        viewer_voted=post.id in voted,
        is_deleted=deleted,
        is_hidden=hidden,
        hidden_reason=post.hidden_reason if hidden and privileged else None,
        edited_at=post.edited_at,
        created_at=post.created_at,
    )


def thread_out(
    question: BountyQAPost,
    replies: list[BountyQAPost],
    bounty: Bounty,
    viewer: User | None,
    voted: set[uuid.UUID],
) -> ThreadOut:
    base = post_out(question, bounty, viewer, voted)
    visible = [r for r in replies if r.deleted_at is None]
    return ThreadOut(
        **base.model_dump(),
        replies=[post_out(r, bounty, viewer, voted) for r in visible],
        reply_count=len(visible),
        answered=any(
            r.is_accepted or (r.author_id == bounty.requester_id and r.hidden_at is None) for r in visible
        ),
    )


async def _thread(
    session: AsyncSession, question: BountyQAPost, bounty: Bounty, viewer: User | None
) -> ThreadOut:
    replies = (await repo.replies_for(session, [question.id])).get(question.id, [])
    voted = (
        await repo.voted_ids(session, viewer.id, [question.id, *[r.id for r in replies]]) if viewer else set()
    )
    return thread_out(question, replies, bounty, viewer, voted)


# --- Loading and rules ---------------------------------------------------------------------------------


def closed_reason(bounty: Bounty) -> str | None:
    if bounty.status == BountyStatus.DRAFT:
        return "Questions open once the bounty is published."
    if bounty.is_hidden:
        return "Questions are closed while the bounty is hidden by moderation."
    if bounty.status in CLOSED_STATUSES:
        return f"Questions are closed because the bounty is {bounty.status.value.lower()}."
    return None


def _require_poster(user: User) -> None:
    if not user.is_active:
        raise Forbidden("This account has been suspended.")
    if user.email_verified_at is None:
        raise Forbidden("Verify your email address before posting questions.", code="email_not_verified")


async def _bounty(session: AsyncSession, bounty_id: uuid.UUID, viewer: User | None) -> Bounty:
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None or not bounty_service.can_view(bounty, viewer):
        raise NotFound("Bounty not found.")
    return bounty


async def _post(
    session: AsyncSession, post_id: uuid.UUID, viewer: User | None
) -> tuple[BountyQAPost, Bounty]:
    post = await session.scalar(select(BountyQAPost).where(BountyQAPost.id == post_id))
    if post is None:
        raise NotFound("Post not found.")
    bounty = await _bounty(session, post.bounty_id, viewer)
    return post, bounty


async def _lock(session: AsyncSession, post_id: uuid.UUID) -> BountyQAPost | None:
    return await session.scalar(
        select(BountyQAPost)
        .where(BountyQAPost.id == post_id)
        .with_for_update(of=BountyQAPost)
        .execution_options(populate_existing=True)
    )


async def _post_for_update(
    session: AsyncSession, post_id: uuid.UUID, viewer: User
) -> tuple[BountyQAPost, Bounty]:
    """Locks one post. The bounty is only read (a post never changes it), so no bounty lock is taken."""
    post, bounty = await _post(session, post_id, viewer)
    return await _lock(session, post_id) or post, bounty


async def _thread_for_update(
    session: AsyncSession, post_id: uuid.UUID, viewer: User
) -> tuple[BountyQAPost, BountyQAPost, Bounty]:
    """Locks a whole thread for a change that touches its siblings (accepting an answer): the question first,
    then the post itself, which is the fixed parent-before-child order every writer here uses."""
    post, bounty = await _post(session, post_id, viewer)
    question = await _lock(session, post.parent_id or post.id)
    if question is None:
        raise NotFound("Post not found.")
    locked = question if question.id == post.id else await _lock(session, post_id)
    if locked is None:
        raise NotFound("Post not found.")
    return locked, question, bounty


async def _question_of(session: AsyncSession, post: BountyQAPost) -> BountyQAPost:
    if post.parent_id is None:
        return post
    question = await session.get(BountyQAPost, post.parent_id)
    if question is None:
        raise NotFound("Post not found.")
    return question


def _payload(
    bounty: Bounty, post: BountyQAPost, question: BountyQAPost, participants: list[uuid.UUID], **extra: Any
) -> dict[str, Any]:
    return {
        "bounty_id": bounty.id,
        "requester_id": bounty.requester_id,
        "title": bounty.title,
        "post_id": post.id,
        "question_id": question.id,
        "author_id": post.author_id,
        "asker_id": question.author_id,
        "participant_ids": participants,
        "link": question_link(bounty, question.id),
        **extra,
    }


async def _done(session: AsyncSession, bounty: Bounty) -> None:
    await session.commit()
    await invalidate_bounty(str(bounty.id), bounty.slug)  # question counts on cards and detail


# --- Reads ----------------------------------------------------------------------------------------------


async def list_threads(
    session: AsyncSession, bounty_ref: str, viewer: User | None, sort: QASort, params: PageParams
) -> QuestionPage:
    bounty = await bounty_repo.get_by_id_or_slug(session, bounty_ref)
    if bounty is None or not bounty_service.can_view(bounty, viewer):
        raise NotFound("Bounty not found.")
    base = repo.listed_questions(bounty.id)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    questions = list(
        (await session.scalars(repo.ordered(base, sort).offset(params.offset).limit(params.page_size)))
        .unique()
        .all()
    )
    replies = await repo.replies_for(session, [q.id for q in questions])
    all_ids = [q.id for q in questions] + [r.id for rs in replies.values() for r in rs]
    voted = await repo.voted_ids(session, viewer.id, all_ids) if viewer else set()
    items = [thread_out(q, replies.get(q.id, []), bounty, viewer, voted) for q in questions]
    reason = closed_reason(bounty)
    page = Page[ThreadOut].build(items, total, params)
    return QuestionPage(
        **page.model_dump(exclude={"items"}),
        items=items,
        questions_count=(await repo.question_counts(session, [bounty.id])).get(bounty.id, 0),
        can_ask=viewer is not None and viewer.is_active and reason is None,
        closed_reason=reason,
        viewer_is_requester=viewer is not None and viewer.id == bounty.requester_id,
        viewer_is_moderator=_is_moderator(viewer),
    )


# --- Writes ----------------------------------------------------------------------------------------------


async def ask(session: AsyncSession, user: User, bounty_id: uuid.UUID, body: str) -> ThreadOut:
    _require_poster(user)
    await hit("qa:post:user", str(user.id), 20, 600)
    bounty = await _bounty(session, bounty_id, user)
    reason = closed_reason(bounty)
    if reason:
        raise InvalidStateTransition(reason)
    question = BountyQAPost(
        id=uuid.uuid4(), bounty_id=bounty.id, author_id=user.id, parent_id=None, body=body
    )
    session.add(question)
    await session.flush()
    audit.record(
        session,
        actor_id=user.id,
        action="qa.question_created",
        entity_type="qa_post",
        entity_id=question.id,
        bounty_id=bounty.id,
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.QA_QUESTION_CREATED,
        aggregate_type="qa_post",
        aggregate_id=question.id,
        actor_id=user.id,
        payload=_payload(bounty, question, question, []),
    )
    await _done(session, bounty)
    await session.refresh(question)
    return await _thread(session, question, bounty, user)


async def reply(session: AsyncSession, user: User, post_id: uuid.UUID, body: str) -> ThreadOut:
    """Replies go one level deep: replying to a reply adds to the same question's thread."""
    _require_poster(user)
    await hit("qa:post:user", str(user.id), 20, 600)
    post, bounty = await _post(session, post_id, user)
    question = await _question_of(session, post)
    if not question.is_visible:
        raise InvalidStateTransition("This question can no longer be answered.")
    reason = closed_reason(bounty)
    if reason:
        raise InvalidStateTransition(reason)
    answer = BountyQAPost(
        id=uuid.uuid4(), bounty_id=bounty.id, author_id=user.id, parent_id=question.id, body=body
    )
    session.add(answer)
    await session.flush()
    participants = await repo.thread_participants(session, question, exclude=user.id)
    audit.record(
        session,
        actor_id=user.id,
        action="qa.reply_created",
        entity_type="qa_post",
        entity_id=answer.id,
        bounty_id=bounty.id,
        metadata={"question_id": str(question.id)},
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.QA_REPLY_CREATED,
        aggregate_type="qa_post",
        aggregate_id=answer.id,
        actor_id=user.id,
        payload=_payload(
            bounty, answer, question, participants, is_requester_answer=user.id == bounty.requester_id
        ),
    )
    await _done(session, bounty)
    return await _thread(session, question, bounty, user)


async def edit(session: AsyncSession, user: User, post_id: uuid.UUID, body: str) -> ThreadOut:
    post, bounty = await _post_for_update(session, post_id, user)
    if post.author_id != user.id:
        raise Forbidden("You can only edit your own posts.")
    if post.deleted_at is not None:
        raise InvalidStateTransition("This post was deleted.")
    if post.hidden_at is not None:
        raise InvalidStateTransition("A moderator hid this post, so it cannot be edited.")
    if post.parent_id is None and len(body) < QUESTION_MIN:
        raise ValidationFailed(
            f"A question needs at least {QUESTION_MIN} characters.",
            details=[{"field": "body", "message": f"At least {QUESTION_MIN} characters"}],
        )
    if body != post.body:
        post.body = body
        post.edited_at = utcnow()
        audit.record(
            session,
            actor_id=user.id,
            action="qa.post_edited",
            entity_type="qa_post",
            entity_id=post.id,
            bounty_id=bounty.id,
            is_public=False,
        )
    await session.commit()
    question = await _question_of(session, post)
    return await _thread(session, question, bounty, user)


async def remove(session: AsyncSession, user: User, post_id: uuid.UUID) -> None:
    post, bounty = await _post_for_update(session, post_id, user)
    if post.author_id != user.id:
        raise Forbidden("You can only delete your own posts.")
    if post.deleted_at is not None:
        return
    post.deleted_at = utcnow()
    post.body = ""
    post.is_pinned = False
    post.is_accepted = False
    audit.record(
        session,
        actor_id=user.id,
        action="qa.post_deleted",
        entity_type="qa_post",
        entity_id=post.id,
        bounty_id=bounty.id,
        is_public=False,
    )
    await _done(session, bounty)


async def vote(session: AsyncSession, user: User, post_id: uuid.UUID, *, up: bool) -> VoteOut:
    """One upvote per user per post. The vote row and the counter move together in one transaction; the counter
    is changed in SQL and read back with RETURNING, so concurrent votes cannot lose one another."""
    await hit("qa:vote", str(user.id), 120, 3600)
    post, _bounty_row = await _post(session, post_id, user)
    if up:
        if post.author_id == user.id:
            raise Forbidden("You cannot upvote your own post.")
        if not post.is_visible:
            raise InvalidStateTransition("This post can no longer be upvoted.")
        changed = await session.scalar(
            insert(BountyQAVote)
            .values(post_id=post.id, user_id=user.id)
            .on_conflict_do_nothing()
            .returning(BountyQAVote.post_id)
        )
        delta = BountyQAPost.upvotes_count + 1
    else:
        changed = await session.scalar(
            delete(BountyQAVote)
            .where(BountyQAVote.post_id == post.id, BountyQAVote.user_id == user.id)
            .returning(BountyQAVote.post_id)
        )
        delta = func.greatest(BountyQAPost.upvotes_count - 1, 0)
    if changed is not None:
        count = await session.scalar(
            update(BountyQAPost)
            .where(BountyQAPost.id == post.id)
            .values(upvotes_count=delta)
            .returning(BountyQAPost.upvotes_count)
        )
    else:  # already in that state; report what the row holds
        count = await session.scalar(select(BountyQAPost.upvotes_count).where(BountyQAPost.id == post.id))
    await session.commit()
    return VoteOut(post_id=post.id, upvotes=int(count or 0), viewer_voted=up)


def _require_requester(bounty: Bounty, user: User, action: str) -> None:
    if bounty.requester_id != user.id:
        raise Forbidden(f"Only the bounty's requester can {action}.")


async def set_accepted(session: AsyncSession, user: User, post_id: uuid.UUID, *, accepted: bool) -> ThreadOut:
    post, question, bounty = await _thread_for_update(session, post_id, user)
    _require_requester(bounty, user, "accept answers")
    if post.parent_id is None:
        raise ValidationFailed("Only a reply can be accepted as the answer.")
    if accepted and not post.is_visible:
        raise InvalidStateTransition("A deleted or hidden reply cannot be accepted.")
    if accepted and not post.is_accepted:
        # One accepted answer per question: clear the previous one first (a partial unique index enforces it).
        await session.execute(
            update(BountyQAPost)
            .where(
                BountyQAPost.parent_id == question.id, BountyQAPost.is_accepted, BountyQAPost.id != post.id
            )
            .values(is_accepted=False)
        )
        await session.flush()
        post.is_accepted = True
        audit.record(
            session,
            actor_id=user.id,
            action="qa.reply_accepted",
            entity_type="qa_post",
            entity_id=post.id,
            bounty_id=bounty.id,
            metadata={"question_id": str(question.id)},
            is_public=False,
        )
        add_event(
            session,
            event_type=EventType.QA_REPLY_ACCEPTED,
            aggregate_type="qa_post",
            aggregate_id=post.id,
            actor_id=user.id,
            payload=_payload(bounty, post, question, [post.author_id]),
        )
    elif not accepted and post.is_accepted:
        post.is_accepted = False
        audit.record(
            session,
            actor_id=user.id,
            action="qa.reply_unaccepted",
            entity_type="qa_post",
            entity_id=post.id,
            bounty_id=bounty.id,
            is_public=False,
        )
    await session.commit()
    return await _thread(session, question, bounty, user)


async def set_pinned(session: AsyncSession, user: User, post_id: uuid.UUID, *, pinned: bool) -> ThreadOut:
    post, bounty = await _post_for_update(session, post_id, user)
    _require_requester(bounty, user, "pin questions")
    if post.parent_id is not None:
        raise ValidationFailed("Pin the question; replies stay with their thread.")
    if pinned and not post.is_visible:
        raise InvalidStateTransition("A deleted or hidden question cannot be pinned.")
    if pinned and not post.is_pinned:
        if await repo.pinned_count(session, bounty.id) >= MAX_PINNED:
            raise ValidationFailed(f"Up to {MAX_PINNED} questions can be pinned. Unpin one first.")
        post.is_pinned = True
    elif not pinned:
        post.is_pinned = False
    audit.record(
        session,
        actor_id=user.id,
        action="qa.question_pinned" if pinned else "qa.question_unpinned",
        entity_type="qa_post",
        entity_id=post.id,
        bounty_id=bounty.id,
        is_public=False,
    )
    await session.commit()
    return await _thread(session, post, bounty, user)


async def report(session: AsyncSession, user: User, post_id: uuid.UUID, reason: str) -> UserReport:
    from app.modules.admin.service import create_report  # admin owns report persistence and the queue

    post, _bounty_row = await _post(session, post_id, user)
    if post.author_id == user.id:
        raise ValidationFailed("You cannot report your own post.")
    if post.deleted_at is not None:
        raise InvalidStateTransition("This post was deleted.")
    return await create_report(
        session, reporter=user, target_type=ReportTarget.QA_POST, target_id=post.id, reason=reason
    )


async def moderate(
    session: AsyncSession, moderator: User, post_id: uuid.UUID, action: str, reason: str
) -> ModeratedPostOut:
    """Hide or unhide a post. Hiding also marks the post's open reports as actioned."""
    post, bounty = await _post_for_update(session, post_id, moderator)
    now = utcnow()
    question = await _question_of(session, post)
    if action == "HIDE" and post.hidden_at is None:
        post.hidden_at = now
        post.hidden_by_id = moderator.id
        post.hidden_reason = reason
        post.is_pinned = False
        post.is_accepted = False
        await session.execute(
            update(UserReport)
            .where(
                UserReport.target_type == ReportTarget.QA_POST,
                UserReport.target_id == post.id,
                UserReport.status.in_(OPEN_REPORT_STATUSES),
            )
            .values(
                status=ReportStatus.ACTIONED,
                resolution_note=f"Post hidden: {reason}"[:2000],
                resolved_by_id=moderator.id,
                resolved_at=now,
            )
        )
        add_event(
            session,
            event_type=EventType.QA_POST_HIDDEN,
            aggregate_type="qa_post",
            aggregate_id=post.id,
            actor_id=moderator.id,
            payload=_payload(bounty, post, question, [post.author_id]),
        )
    elif action == "UNHIDE" and post.hidden_at is not None:
        post.hidden_at = None
        post.hidden_by_id = None
        post.hidden_reason = None
    else:
        raise InvalidStateTransition(
            "This post is already hidden." if action == "HIDE" else "This post is not hidden."
        )
    audit.record(
        session,
        actor_id=moderator.id,
        action=f"qa.post_{'hidden' if action == 'HIDE' else 'unhidden'}",
        entity_type="qa_post",
        entity_id=post.id,
        bounty_id=bounty.id,
        metadata={"reason": reason, "question_id": str(question.id)},
        is_public=False,
    )
    await _done(session, bounty)
    await session.refresh(post)
    out = post_out(post, bounty, moderator, set())
    return ModeratedPostOut(**out.model_dump(), bounty_id=bounty.id, bounty_slug=bounty.slug)


# --- Moderation queue (admin reports) ----------------------------------------------------------------


async def report_target_summaries(
    session: AsyncSession, post_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """What a moderator needs next to a reported post: where it is, an excerpt, and whether it is hidden."""
    if not post_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(BountyQAPost, Bounty)
                .join(Bounty, Bounty.id == BountyQAPost.bounty_id)
                .where(BountyQAPost.id.in_(post_ids))
            )
        )
        .unique()
        .all()
    )
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for post, bounty in rows:
        kind = "Question" if post.parent_id is None else "Reply"
        excerpt = (
            None
            if post.deleted_at
            else (post.body[:EXCERPT_LENGTH] + ("…" if len(post.body) > EXCERPT_LENGTH else ""))
        )
        out[post.id] = {
            "label": f"{kind} on “{bounty.title}”",
            "excerpt": excerpt,
            "link": question_link(bounty, post.parent_id or post.id),
            "author": bounty_service.user_summary(post.author),
            "is_hidden": post.hidden_at is not None,
            "is_deleted": post.deleted_at is not None,
            "bounty_id": bounty.id,
        }
    return out
