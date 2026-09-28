"""Domain event -> notification recipient/content mapping (pure)."""

from __future__ import annotations

import uuid

import pytest

from app.messaging.events import EventEnvelope, EventType
from app.messaging.schemas import validate_payload
from app.modules.notifications.handlers import HANDLED_EVENT_TYPES, build_notifications
from app.modules.notifications.models import NotificationType

REQUESTER = uuid.uuid4()
CONTRIBUTOR = uuid.uuid4()
BOUNTY = uuid.uuid4()
TITLE = "Build a Soroban indexer"


def envelope(event_type: str, payload: dict, actor: uuid.UUID | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        aggregate_type="bounty",
        aggregate_id=BOUNTY,
        actor_id=actor,
        payload=validate_payload(event_type, payload),
    )


def app_payload(status: str = "PENDING") -> dict:
    return {
        "application_id": uuid.uuid4(),
        "bounty_id": BOUNTY,
        "requester_id": REQUESTER,
        "contributor_id": CONTRIBUTOR,
        "title": TITLE,
        "status": status,
    }


def sub_payload(status: str = "SUBMITTED", version: int = 1) -> dict:
    return {
        "submission_id": uuid.uuid4(),
        "bounty_id": BOUNTY,
        "requester_id": REQUESTER,
        "contributor_id": CONTRIBUTOR,
        "title": TITLE,
        "status": status,
        "version": version,
    }


def pay_payload() -> dict:
    return {
        "bounty_id": BOUNTY,
        "requester_id": REQUESTER,
        "contributor_id": CONTRIBUTOR,
        "title": TITLE,
        "amount": "250.5000000",
        "transaction_id": uuid.uuid4(),
    }


def test_application_created_notifies_requester_with_review_link() -> None:
    [spec] = build_notifications(envelope(EventType.APPLICATION_CREATED, app_payload(), actor=CONTRIBUTOR))
    assert spec.user_id == REQUESTER
    assert spec.notification_type == NotificationType.APPLICATION_RECEIVED
    assert spec.link == f"/app/bounties/{BOUNTY}/applications"
    assert TITLE in spec.message


@pytest.mark.parametrize(
    ("event_type", "expected_type"),
    [
        (EventType.APPLICATION_ACCEPTED, NotificationType.APPLICATION_ACCEPTED),
        (EventType.APPLICATION_REJECTED, NotificationType.APPLICATION_REJECTED),
    ],
)
def test_application_decisions_notify_contributor(event_type: str, expected_type: NotificationType) -> None:
    [spec] = build_notifications(envelope(event_type, app_payload("ACCEPTED"), actor=REQUESTER))
    assert spec.user_id == CONTRIBUTOR
    assert spec.notification_type == expected_type
    assert spec.link == "/app/applications"


def test_submission_created_and_resubmitted_notify_requester() -> None:
    [created] = build_notifications(envelope(EventType.SUBMISSION_CREATED, sub_payload(), actor=CONTRIBUTOR))
    [resubmitted] = build_notifications(
        envelope(EventType.SUBMISSION_RESUBMITTED, sub_payload("RESUBMITTED", 2), actor=CONTRIBUTOR)
    )
    for spec in (created, resubmitted):
        assert spec.user_id == REQUESTER
        assert spec.notification_type == NotificationType.SUBMISSION_RECEIVED
        assert spec.link == f"/app/bounties/{BOUNTY}/submissions"
    assert "version 2" in resubmitted.message


@pytest.mark.parametrize(
    ("event_type", "expected_type"),
    [
        (EventType.SUBMISSION_REVISION_REQUESTED, NotificationType.REVISION_REQUESTED),
        (EventType.SUBMISSION_APPROVED, NotificationType.SUBMISSION_APPROVED),
        (EventType.SUBMISSION_REJECTED, NotificationType.SUBMISSION_REJECTED),
    ],
)
def test_submission_reviews_notify_contributor(event_type: str, expected_type: NotificationType) -> None:
    [spec] = build_notifications(envelope(event_type, sub_payload(), actor=REQUESTER))
    assert spec.user_id == CONTRIBUTOR
    assert spec.notification_type == expected_type
    assert spec.link == "/app/submissions"


def test_payment_confirmed_notifies_both_parties_when_actor_is_system() -> None:
    specs = build_notifications(envelope(EventType.PAYMENT_CONFIRMED, pay_payload()))
    assert {s.user_id for s in specs} == {REQUESTER, CONTRIBUTOR}
    assert all(s.notification_type == NotificationType.PAYMENT_CONFIRMED for s in specs)
    assert all(s.link == "/app/payments" for s in specs)
    contributor = next(s for s in specs if s.user_id == CONTRIBUTOR)
    requester = next(s for s in specs if s.user_id == REQUESTER)
    assert (contributor.title, requester.title) == ("Payment received", "Payout confirmed")
    assert "250.5 XLM" in contributor.message


def test_actor_is_never_notified_about_own_action() -> None:
    specs = build_notifications(envelope(EventType.PAYMENT_CONFIRMED, pay_payload(), actor=REQUESTER))
    assert [s.user_id for s in specs] == [CONTRIBUTOR]
    assert build_notifications(envelope(EventType.APPLICATION_CREATED, app_payload(), actor=REQUESTER)) == []


def test_dispute_events_notify_both_parties_except_actor() -> None:
    payload = {
        "bounty_id": BOUNTY,
        "dispute_id": uuid.uuid4(),
        "requester_id": REQUESTER,
        "contributor_id": CONTRIBUTOR,
        "title": TITLE,
        "status": "OPEN",
    }
    [raised] = build_notifications(envelope(EventType.DISPUTE_RAISED, payload, actor=CONTRIBUTOR))
    assert raised.user_id == REQUESTER
    assert raised.notification_type == NotificationType.DISPUTE_UPDATE
    assert raised.link == f"/app/bounties/{BOUNTY}"

    resolved = build_notifications(
        envelope(
            EventType.DISPUTE_RESOLVED, {**payload, "status": "RESOLVED", "resolution": "REFUND_TO_REQUESTER"}
        )
    )
    assert {s.user_id for s in resolved} == {REQUESTER, CONTRIBUTOR}
    assert all("refunded to the requester" in s.message for s in resolved)


def test_bounty_funded_and_expired_notify_requester() -> None:
    base = {"bounty_id": BOUNTY, "requester_id": REQUESTER, "title": TITLE, "status": "FUNDED"}
    [funded] = build_notifications(envelope(EventType.BOUNTY_FUNDED, base))
    assert funded.notification_type == NotificationType.BOUNTY_FUNDED
    assert funded.link == f"/app/bounties/{BOUNTY}"
    [expired] = build_notifications(envelope(EventType.BOUNTY_EXPIRED, {**base, "status": "EXPIRED"}))
    assert expired.notification_type == NotificationType.BOUNTY_EXPIRED


def test_cancellation_fans_out_to_optional_contributors_without_duplicates() -> None:
    other = uuid.uuid4()
    payload = {
        "bounty_id": BOUNTY,
        "requester_id": REQUESTER,
        "title": TITLE,
        "status": "CANCELLED",
        "contributor_ids": [str(CONTRIBUTOR), str(CONTRIBUTOR)],
        "applicant_ids": [str(other)],
    }
    specs = build_notifications(envelope(EventType.BOUNTY_CANCELLED, payload, actor=REQUESTER))
    assert sorted(str(s.user_id) for s in specs) == sorted([str(CONTRIBUTOR), str(other)])
    assert all(s.link == f"/bounties/{BOUNTY}" for s in specs)


def test_unmapped_events_produce_nothing() -> None:
    payload = {"bounty_id": BOUNTY, "requester_id": REQUESTER, "title": TITLE, "status": "DRAFT"}
    assert build_notifications(envelope(EventType.BOUNTY_CREATED, payload)) == []
    assert EventType.BOUNTY_CREATED not in HANDLED_EVENT_TYPES


def test_payload_context_carries_ids_but_no_free_text() -> None:
    [spec] = build_notifications(envelope(EventType.APPLICATION_CREATED, app_payload(), actor=CONTRIBUTOR))
    assert spec.payload["bounty_id"] == str(BOUNTY)
    assert spec.payload["event_type"] == EventType.APPLICATION_CREATED
    assert "title" not in spec.payload
