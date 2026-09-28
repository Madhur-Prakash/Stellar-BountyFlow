"""Domain event types, topics, and the versioned event envelope."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Topics:
    BOUNTY = "bounty.events"
    APPLICATION = "application.events"
    SUBMISSION = "submission.events"
    PAYMENT = "payment.events"
    NOTIFICATION = "notification.events"
    ANALYTICS = "analytics.events"
    BLOCKCHAIN = "blockchain.events"
    EMAIL = "email.events"

    ALL = (BOUNTY, APPLICATION, SUBMISSION, PAYMENT, NOTIFICATION, ANALYTICS, BLOCKCHAIN, EMAIL)

    @staticmethod
    def dlq(topic: str) -> str:
        return f"{topic}.dlq"


class EventType:
    USER_REGISTERED = "user.registered"
    USER_EMAIL_VERIFIED = "user.email_verified"
    WALLET_VERIFIED = "wallet.verified"
    EMAIL_VERIFICATION_REQUESTED = "email.verification_requested"
    PASSWORD_RESET_REQUESTED = "email.password_reset_requested"
    NOTIFICATION_CREATED = "notification.created"

    BOUNTY_CREATED = "bounty.created"
    BOUNTY_UPDATED = "bounty.updated"
    BOUNTY_PUBLISHED = "bounty.published"
    BOUNTY_FUNDING_SUBMITTED = "bounty.funding_submitted"
    BOUNTY_FUNDED = "bounty.funded"
    BOUNTY_STATUS_CHANGED = "bounty.status_changed"
    BOUNTY_CANCEL_REQUESTED = "bounty.cancel_requested"
    BOUNTY_CANCELLED = "bounty.cancelled"
    BOUNTY_EXPIRED = "bounty.expired"
    BOUNTY_COMPLETED = "bounty.completed"
    BOUNTY_DEADLINE_APPROACHING = "bounty.deadline_approaching"
    DISPUTE_RAISED = "bounty.dispute_raised"
    DISPUTE_UPDATED = "bounty.dispute_updated"
    DISPUTE_RESOLVED = "bounty.dispute_resolved"

    APPLICATION_CREATED = "application.created"
    APPLICATION_ACCEPTED = "application.accepted"
    APPLICATION_REJECTED = "application.rejected"
    APPLICATION_WITHDRAWN = "application.withdrawn"

    SUBMISSION_CREATED = "submission.created"
    SUBMISSION_RESUBMITTED = "submission.resubmitted"
    SUBMISSION_REVISION_REQUESTED = "submission.revision_requested"
    SUBMISSION_APPROVED = "submission.approved"
    SUBMISSION_REJECTED = "submission.rejected"

    PAYMENT_CONFIRMED = "payment.confirmed"
    PAYMENT_FAILED = "payment.failed"
    REFUND_CONFIRMED = "payment.refund_confirmed"

    TX_SUBMITTED = "blockchain.transaction_submitted"
    TX_CONFIRMED = "blockchain.transaction_confirmed"
    TX_FAILED = "blockchain.transaction_failed"


# Default topic for each event-type prefix.
_TOPIC_BY_PREFIX = {
    "user": Topics.ANALYTICS,
    "wallet": Topics.ANALYTICS,
    "email": Topics.EMAIL,
    "notification": Topics.NOTIFICATION,
    "bounty": Topics.BOUNTY,
    "application": Topics.APPLICATION,
    "submission": Topics.SUBMISSION,
    "payment": Topics.PAYMENT,
    "blockchain": Topics.BLOCKCHAIN,
}


def topic_for(event_type: str) -> str:
    return _TOPIC_BY_PREFIX.get(event_type.split(".", 1)[0], Topics.ANALYTICS)


class EventEnvelope(BaseModel):
    """Every message on Kafka uses this envelope."""

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    event_type: str
    schema_version: int = 1
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    aggregate_type: str
    aggregate_id: uuid.UUID
    correlation_id: str | None = None
    actor_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
