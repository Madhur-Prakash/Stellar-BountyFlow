"""Q&A and pull request events -> notification recipients and content (pure)."""

from __future__ import annotations

import uuid

from app.messaging.events import EventEnvelope, EventType, Topics, topic_for
from app.messaging.schemas import validate_payload
from app.modules.notifications.handlers import HANDLED_EVENT_TYPES, build_notifications
from app.modules.notifications.models import NotificationType

REQUESTER, ASKER, REPLIER, OTHER = (uuid.uuid4() for _ in range(4))
BOUNTY, QUESTION, POST = (uuid.uuid4() for _ in range(3))
TITLE = "Build a Soroban indexer"


def qa(
    event_type: str, *, author: uuid.UUID, actor: uuid.UUID, participants: list[uuid.UUID], **extra: object
) -> EventEnvelope:
    payload = {
        "bounty_id": BOUNTY,
        "requester_id": REQUESTER,
        "title": TITLE,
        "post_id": POST,
        "question_id": QUESTION,
        "author_id": author,
        "asker_id": ASKER,
        "participant_ids": participants,
        "link": f"/bounties/soroban-indexer#q-{QUESTION}",
        **extra,
    }
    return EventEnvelope(
        event_type=event_type,
        aggregate_type="qa_post",
        aggregate_id=POST,
        actor_id=actor,
        payload=validate_payload(event_type, payload),
    )


def test_qa_events_travel_on_the_bounty_topic() -> None:
    for et in (EventType.QA_QUESTION_CREATED, EventType.QA_REPLY_CREATED, EventType.QA_REPLY_ACCEPTED):
        assert topic_for(et) == Topics.BOUNTY
        assert et in HANDLED_EVENT_TYPES
    assert topic_for(EventType.SUBMISSION_PULL_REQUEST_UPDATED) == Topics.SUBMISSION
    assert topic_for(EventType.GITHUB_ACCOUNT_LINKED) == Topics.ANALYTICS


def test_new_question_notifies_the_requester_with_a_thread_link() -> None:
    [spec] = build_notifications(
        qa(EventType.QA_QUESTION_CREATED, author=ASKER, actor=ASKER, participants=[])
    )
    assert spec.user_id == REQUESTER
    assert spec.notification_type == NotificationType.QUESTION_RECEIVED
    assert spec.link == f"/bounties/soroban-indexer#q-{QUESTION}"
    assert TITLE in spec.message


def test_question_by_the_requester_notifies_nobody() -> None:
    assert (
        build_notifications(
            qa(EventType.QA_QUESTION_CREATED, author=REQUESTER, actor=REQUESTER, participants=[])
        )
        == []
    )


def test_reply_notifies_the_asker_and_participants_but_not_the_replier() -> None:
    specs = build_notifications(
        qa(EventType.QA_REPLY_CREATED, author=REPLIER, actor=REPLIER, participants=[ASKER, OTHER, REPLIER])
    )
    assert {s.user_id for s in specs} == {ASKER, OTHER}
    assert all(s.notification_type == NotificationType.QUESTION_REPLY for s in specs)
    assert all(s.title == "New reply" for s in specs)


def test_requester_answer_is_marked_as_theirs() -> None:
    specs = build_notifications(
        qa(
            EventType.QA_REPLY_CREATED,
            author=REQUESTER,
            actor=REQUESTER,
            participants=[ASKER],
            is_requester_answer=True,
        )
    )
    assert [s.user_id for s in specs] == [ASKER]
    assert specs[0].title == "The requester answered"


def test_accepted_answer_notifies_its_author_and_the_asker() -> None:
    specs = build_notifications(
        qa(EventType.QA_REPLY_ACCEPTED, author=REPLIER, actor=REQUESTER, participants=[REPLIER])
    )
    assert {(s.user_id, s.title) for s in specs} == {
        (REPLIER, "Your answer was accepted"),
        (ASKER, "Your question has an answer"),
    }


def test_hidden_post_tells_its_author() -> None:
    moderator = uuid.uuid4()
    [spec] = build_notifications(
        qa(EventType.QA_POST_HIDDEN, author=REPLIER, actor=moderator, participants=[REPLIER])
    )
    assert (spec.user_id, spec.title) == (REPLIER, "Your post was hidden")


def pr_event(state: str, previous: str = "OPEN") -> EventEnvelope:
    contributor = uuid.uuid4()
    payload = {
        "submission_id": uuid.uuid4(),
        "bounty_id": BOUNTY,
        "requester_id": REQUESTER,
        "contributor_id": contributor,
        "title": TITLE,
        "status": "SUBMITTED",
        "version": 1,
        "pull_request_id": uuid.uuid4(),
        "repository": "stellar/js-stellar-sdk",
        "number": 1744,
        "state": state,
        "previous_state": previous,
        "verification": "VERIFIED",
    }
    return EventEnvelope(
        event_type=EventType.SUBMISSION_PULL_REQUEST_UPDATED,
        aggregate_type="submission",
        aggregate_id=uuid.uuid4(),
        payload=validate_payload(EventType.SUBMISSION_PULL_REQUEST_UPDATED, payload),
    )


def test_merged_pull_request_notifies_both_sides() -> None:
    specs = build_notifications(pr_event("MERGED"))
    assert len(specs) == 2
    assert all(s.notification_type == NotificationType.PULL_REQUEST_UPDATE for s in specs)
    requester = next(s for s in specs if s.user_id == REQUESTER)
    assert requester.message == (
        f"stellar/js-stellar-sdk#1744, linked to a submission for “{TITLE}”, was merged."
    )
    assert requester.link == f"/app/bounties/{BOUNTY}/submissions"


def test_closed_pull_request_is_reported_and_other_changes_are_silent() -> None:
    assert {s.title for s in build_notifications(pr_event("CLOSED"))} == {"Pull request closed"}
    assert build_notifications(pr_event("OPEN", previous="CLOSED")) == []
