"""Bounty Q&A end to end: threads, requester answers, accepted and pinned posts, edits and deletes, votes,
reports into the moderation queue, moderator hide/unhide with an audit trail, counts, limits, and notifications."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AuditLog
from app.modules.notifications.models import Notification, NotificationType
from app.modules.users.models import Role
from tests.integration.api.conftest import ApiClient, drain_events, register, verify_email
from tests.integration.security.helpers import new_requester, published, set_role


async def verified(client_factory: Any, mail: Any, name: str) -> ApiClient:
    client = client_factory()
    await register(client, name)
    await verify_email(client, mail)
    return client


async def test_questions_threads_answers_and_moderation(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    requester, _ = await new_requester(client_factory, outbox_mail, "qa_owner")
    bounty = await published(requester, repository_url="https://github.com/stellar/js-stellar-sdk")
    bid, slug = bounty["id"], bounty["slug"]
    asker = await verified(client_factory, outbox_mail, "qa_asker")
    helper = await verified(client_factory, outbox_mail, "qa_helper")
    anon = client_factory()

    empty = await anon.get(f"/bounties/{slug}/questions")
    assert empty["items"] == [] and empty["questions_count"] == 0
    assert empty["can_ask"] is False and empty["closed_reason"] is None

    thread = await asker.post(
        f"/bounties/{bid}/questions",
        {"body": "  Does the widget need **dark mode** support?  "},
        expected=201,
    )
    qid = thread["id"]
    assert thread["body"] == "Does the widget need **dark mode** support?"  # trimmed, Markdown kept raw
    assert thread["question_id"] == qid and thread["parent_id"] is None
    assert thread["is_mine"] is True and thread["is_requester"] is False

    answer = await requester.post(
        f"/qa/posts/{qid}/replies", {"body": "Yes, follow the theme tokens."}, expected=201
    )
    reply_id = answer["replies"][0]["id"]
    assert answer["replies"][0]["is_requester"] is True
    assert answer["answered"] is True

    # Replies are one level deep: replying to a reply joins the same thread.
    nested = await helper.post(
        f"/qa/posts/{reply_id}/replies", {"body": "Tokens live in index.css."}, expected=201
    )
    assert nested["id"] == qid and [r["parent_id"] for r in nested["replies"]] == [qid, qid]
    helper_reply = nested["replies"][1]["id"]

    # Only the requester accepts answers and pins questions.
    await asker.request("POST", f"/qa/posts/{reply_id}/accept", expected=403)
    accepted = await requester.post(f"/qa/posts/{helper_reply}/accept")
    assert [r["is_accepted"] for r in accepted["replies"]] == [False, True]
    switched = await requester.post(f"/qa/posts/{reply_id}/accept")
    assert [r["is_accepted"] for r in switched["replies"]] == [
        True,
        False,
    ]  # one accepted answer per question
    await requester.request("POST", f"/qa/posts/{reply_id}/pin", expected=422)  # replies are not pinned
    pinned = await requester.post(f"/qa/posts/{qid}/pin")
    assert pinned["is_pinned"] is True

    # Edits are marked; only the author edits or deletes.
    await helper.request("PATCH", f"/qa/posts/{qid}", json={"body": "Hijacked question text"}, expected=403)
    edited = await asker.patch(f"/qa/posts/{qid}", {"body": "Does the widget need dark mode support too?"})
    assert edited["edited_at"] is not None
    await asker.request("PATCH", f"/qa/posts/{qid}", json={"body": "short"}, expected=422)

    # Upvotes: one per user, never on your own post, and they drive the "helpful" sort.
    second = await helper.post(
        f"/bounties/{bid}/questions", {"body": "Which browsers must be supported?"}, expected=201
    )
    await helper.request("PUT", f"/qa/posts/{second['id']}/vote", expected=403)
    vote = (await asker.request("PUT", f"/qa/posts/{second['id']}/vote", expected=200)).json()
    again = (await asker.request("PUT", f"/qa/posts/{second['id']}/vote", expected=200)).json()
    assert vote["upvotes"] == again["upvotes"] == 1
    await requester.request("PUT", f"/qa/posts/{second['id']}/vote", expected=200)
    await requester.request("POST", f"/qa/posts/{qid}/pin", expected=200)
    await requester.request("DELETE", f"/qa/posts/{qid}/pin", expected=200)
    helpful = await anon.get(f"/bounties/{slug}/questions?sort=helpful")
    assert [t["id"] for t in helpful["items"]] == [second["id"], qid]
    newest = await anon.get(f"/bounties/{slug}/questions?sort=newest")
    assert [t["id"] for t in newest["items"]] == [second["id"], qid]
    viewer = await asker.get(f"/bounties/{slug}/questions?sort=helpful")
    assert viewer["items"][0]["viewer_voted"] is True and viewer["can_ask"] is True
    removed = (await asker.request("DELETE", f"/qa/posts/{second['id']}/vote", expected=200)).json()
    assert removed == {"post_id": second["id"], "upvotes": 1, "viewer_voted": False}

    # Counts on the card and the detail page.
    detail = await anon.get(f"/bounties/{slug}")
    assert detail["questions_count"] == 2
    listing = await anon.get("/bounties?q=escrow")
    assert next(b for b in listing["items"] if b["id"] == bid)["questions_count"] == 2

    # Reporting feeds the moderation queue with context; hiding actions the report and is audited.
    await asker.request(
        "POST", f"/qa/posts/{qid}/report", json={"reason": "This is my own post"}, expected=422
    )
    report = await asker.post(
        f"/qa/posts/{helper_reply}/report", {"reason": "Off-topic advertising link."}, expected=201
    )
    moderator = await verified(client_factory, outbox_mail, "qa_mod")
    await set_role(db_session, moderator, Role.MODERATOR)
    queue = await moderator.get("/admin/reports?target_type=QA_POST")
    [item] = [r for r in queue["items"] if r["id"] == report["id"]]
    assert item["target_summary"]["label"].startswith("Reply on “")
    assert item["target_summary"]["excerpt"] == "Tokens live in index.css."
    assert item["target_summary"]["link"] == f"/bounties/{slug}#q-{qid}"
    await helper.request(
        "POST",
        f"/admin/qa/posts/{helper_reply}/moderate",
        json={"action": "HIDE", "reason": "spam spam"},
        expected=403,
    )
    hidden = await moderator.post(
        f"/admin/qa/posts/{helper_reply}/moderate", {"action": "HIDE", "reason": "Advertising"}
    )
    assert hidden["is_hidden"] is True and hidden["body"] == "Tokens live in index.css."  # staff still see it
    queue = await moderator.get("/admin/reports?target_type=QA_POST")
    resolved = next(r for r in queue["items"] if r["id"] == report["id"])
    assert resolved["status"] == "ACTIONED" and resolved["target_summary"]["is_hidden"] is True

    public = await anon.get(f"/bounties/{slug}/questions")
    thread_view = next(t for t in public["items"] if t["id"] == qid)
    shown = next(r for r in thread_view["replies"] if r["id"] == helper_reply)
    assert shown["is_hidden"] is True and shown["body"] is None and shown["hidden_reason"] is None
    own = next(
        r
        for r in next(
            t for t in (await helper.get(f"/bounties/{slug}/questions"))["items"] if t["id"] == qid
        )["replies"]
        if r["id"] == helper_reply
    )
    assert own["body"] == "Tokens live in index.css." and own["hidden_reason"] == "Advertising"
    await helper.request(
        "PATCH", f"/qa/posts/{helper_reply}", json={"body": "Edited after hiding"}, expected=409
    )
    await moderator.post(
        f"/admin/qa/posts/{helper_reply}/moderate", {"action": "UNHIDE", "reason": "Appeal accepted"}
    )
    actions = (
        await db_session.scalars(
            select(AuditLog.action).where(AuditLog.entity_id == helper_reply).order_by(AuditLog.created_at)
        )
    ).all()
    assert "qa.post_hidden" in actions and "qa.post_unhidden" in actions

    # Soft delete: the thread stays while it has replies; a lone deleted question disappears.
    await helper.request("DELETE", f"/qa/posts/{qid}", expected=403)
    await asker.request("DELETE", f"/qa/posts/{qid}", expected=204)
    kept = next(t for t in (await anon.get(f"/bounties/{slug}/questions"))["items"] if t["id"] == qid)
    assert kept["is_deleted"] is True and kept["body"] is None and kept["author"] is None
    assert len(kept["replies"]) == 2
    await helper.request("DELETE", f"/qa/posts/{second['id']}", expected=204)
    remaining = await anon.get(f"/bounties/{slug}/questions")
    assert [t["id"] for t in remaining["items"]] == [qid]
    assert remaining["questions_count"] == 0  # deleted questions are not counted
    await helper.request("POST", f"/qa/posts/{qid}/replies", json={"body": "Anyone?"}, expected=409)


async def test_posting_rules_and_limits(client_factory: Any, outbox_mail: Any) -> None:
    requester, _ = await new_requester(client_factory, outbox_mail, "qa_rules")
    draft = await requester.post(
        "/bounties",
        {
            "title": "Draft bounty for questions",
            "short_description": "A draft bounty that nobody else can see yet.",
            "description": "The description of a draft bounty that is long enough to be accepted.",
            "category": "DEVELOPMENT",
            "difficulty": "BEGINNER",
            "reward_amount": "5",
        },
        expected=201,
    )
    unverified = client_factory()
    await register(unverified, "qa_unverified")
    await unverified.request(
        "POST",
        f"/bounties/{draft['id']}/questions",
        json={"body": "Is this visible yet?"},
        expected=(403, 404),
    )
    anon = client_factory()
    await anon.request("GET", f"/bounties/{draft['id']}/questions", expected=404)
    owner_view = await requester.get(f"/bounties/{draft['id']}/questions")
    assert (
        owner_view["can_ask"] is False
        and owner_view["closed_reason"] == "Questions open once the bounty is published."
    )

    bounty = await published(requester)
    response = await unverified.request(
        "POST", f"/bounties/{bounty['id']}/questions", json={"body": "Can I ask this?"}
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "email_not_verified"
    asker = await verified(client_factory, outbox_mail, "qa_limits")
    await asker.request(
        "POST", f"/bounties/{bounty['id']}/questions", json={"body": "too short"}, expected=422
    )
    await asker.request(
        "POST", f"/bounties/{bounty['id']}/questions", json={"body": "x" * 5001}, expected=422
    )
    await asker.request(
        "POST", f"/bounties/{bounty['id']}/questions", json={"body": "    padded     "}, expected=422
    )
    for i in range(20):
        await asker.post(
            f"/bounties/{bounty['id']}/questions", {"body": f"Question number {i} about scope"}, expected=201
        )
    limited = await asker.request(
        "POST", f"/bounties/{bounty['id']}/questions", json={"body": "One question too many"}
    )
    assert limited.status_code == 429

    await requester.post(f"/bounties/{bounty['id']}/cancel", {"reason": "Scope moved elsewhere"})
    closed = await asker.get(f"/bounties/{bounty['id']}/questions")
    assert (
        closed["can_ask"] is False
        and closed["closed_reason"] == "Questions are closed because the bounty is cancelled."
    )


async def test_qa_notifications_reach_requester_asker_and_participants(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    requester, _ = await new_requester(client_factory, outbox_mail, "qa_notify")
    bounty = await published(requester)
    asker = await verified(client_factory, outbox_mail, "qa_n_asker")
    other = await verified(client_factory, outbox_mail, "qa_n_other")
    thread = await asker.post(
        f"/bounties/{bounty['id']}/questions", {"body": "Is a demo video required?"}, expected=201
    )
    await other.post(
        f"/qa/posts/{thread['id']}/replies", {"body": "I asked the same thing last week."}, expected=201
    )
    answered = await requester.post(
        f"/qa/posts/{thread['id']}/replies", {"body": "Yes, two minutes is plenty."}, expected=201
    )
    await requester.post(f"/qa/posts/{answered['replies'][1]['id']}/accept")
    outbox_mail.sent.clear()
    await drain_events()

    async def kinds(client: ApiClient) -> list[tuple[str, str]]:
        assert client.me is not None
        rows = (
            await db_session.scalars(
                select(Notification)
                .where(Notification.user_id == client.me["id"])
                .order_by(Notification.created_at)
            )
        ).all()
        return [(n.notification_type.value, n.title) for n in rows]

    assert ("QUESTION_RECEIVED", "New question") in await kinds(requester)
    asker_got = await kinds(asker)
    assert ("QUESTION_REPLY", "New reply") in asker_got
    assert ("QUESTION_REPLY", "The requester answered") in asker_got
    assert ("ANSWER_ACCEPTED", "Your question has an answer") in asker_got
    assert ("QUESTION_REPLY", "The requester answered") in await kinds(other)  # a participant in the thread
    links = (
        await db_session.scalars(
            select(Notification.link).where(
                Notification.notification_type == NotificationType.QUESTION_RECEIVED
            )
        )
    ).all()
    assert links == [f"/bounties/{bounty['slug']}#q-{thread['id']}"]
    # Email goes through the existing outbox and worker, respecting preferences (question alerts email by default).
    subjects = [m.subject for m in outbox_mail.sent]
    assert any(s.startswith("New question") for s in subjects)

    await asker.patch(
        "/notification-preferences", {"types": {"QUESTION_REPLY": {"email": False, "in_app": False}}}
    )
    await other.post(f"/qa/posts/{thread['id']}/replies", {"body": "Thanks, that helps a lot."}, expected=201)
    before = len(await kinds(asker))
    await drain_events()
    assert len(await kinds(asker)) == before  # in-app turned off for replies
