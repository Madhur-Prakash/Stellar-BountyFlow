"""Explicit payload schemas per event type. Payloads are validated when written to the outbox and again
when consumed, so malformed messages are rejected (and dead-lettered) instead of crashing handlers."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.messaging.events import EventType


class _Payload(BaseModel):
    model_config = ConfigDict(extra="allow")


class UserPayload(_Payload):
    user_id: uuid.UUID


class BountyPayload(_Payload):
    bounty_id: uuid.UUID
    requester_id: uuid.UUID
    title: str
    status: str


class BountyStatusPayload(BountyPayload):
    previous_status: str | None = None


class DisputePayload(_Payload):
    bounty_id: uuid.UUID
    dispute_id: uuid.UUID
    requester_id: uuid.UUID
    contributor_id: uuid.UUID | None = None
    title: str
    status: str


class ApplicationPayload(_Payload):
    application_id: uuid.UUID
    bounty_id: uuid.UUID
    requester_id: uuid.UUID
    contributor_id: uuid.UUID
    title: str
    status: str


class SubmissionPayload(_Payload):
    submission_id: uuid.UUID
    bounty_id: uuid.UUID
    requester_id: uuid.UUID
    contributor_id: uuid.UUID
    title: str
    status: str
    version: int


class PaymentPayload(_Payload):
    bounty_id: uuid.UUID
    requester_id: uuid.UUID
    contributor_id: uuid.UUID | None = None
    title: str
    amount: str
    transaction_id: uuid.UUID


class TransactionPayload(_Payload):
    transaction_id: uuid.UUID
    bounty_id: uuid.UUID | None = None
    transaction_type: str
    status: str


class NotificationPayload(_Payload):
    notification_id: uuid.UUID
    user_id: uuid.UUID
    notification_type: str


PAYLOAD_SCHEMAS: dict[str, type[_Payload]] = {
    EventType.USER_REGISTERED: UserPayload,
    EventType.USER_EMAIL_VERIFIED: UserPayload,
    EventType.WALLET_VERIFIED: UserPayload,
    EventType.EMAIL_VERIFICATION_REQUESTED: UserPayload,
    EventType.PASSWORD_RESET_REQUESTED: UserPayload,
    EventType.NOTIFICATION_CREATED: NotificationPayload,
    EventType.BOUNTY_CREATED: BountyPayload,
    EventType.BOUNTY_UPDATED: BountyPayload,
    EventType.BOUNTY_PUBLISHED: BountyPayload,
    EventType.BOUNTY_FUNDING_SUBMITTED: BountyPayload,
    EventType.BOUNTY_FUNDED: BountyStatusPayload,
    EventType.BOUNTY_STATUS_CHANGED: BountyStatusPayload,
    EventType.BOUNTY_CANCEL_REQUESTED: BountyStatusPayload,
    EventType.BOUNTY_CANCELLED: BountyStatusPayload,
    EventType.BOUNTY_EXPIRED: BountyStatusPayload,
    EventType.BOUNTY_COMPLETED: BountyStatusPayload,
    EventType.BOUNTY_DEADLINE_APPROACHING: BountyPayload,
    EventType.DISPUTE_RAISED: DisputePayload,
    EventType.DISPUTE_UPDATED: DisputePayload,
    EventType.DISPUTE_RESOLVED: DisputePayload,
    EventType.APPLICATION_CREATED: ApplicationPayload,
    EventType.APPLICATION_ACCEPTED: ApplicationPayload,
    EventType.APPLICATION_REJECTED: ApplicationPayload,
    EventType.APPLICATION_WITHDRAWN: ApplicationPayload,
    EventType.SUBMISSION_CREATED: SubmissionPayload,
    EventType.SUBMISSION_RESUBMITTED: SubmissionPayload,
    EventType.SUBMISSION_REVISION_REQUESTED: SubmissionPayload,
    EventType.SUBMISSION_APPROVED: SubmissionPayload,
    EventType.SUBMISSION_REJECTED: SubmissionPayload,
    EventType.PAYMENT_CONFIRMED: PaymentPayload,
    EventType.PAYMENT_FAILED: PaymentPayload,
    EventType.REFUND_CONFIRMED: PaymentPayload,
    EventType.TX_SUBMITTED: TransactionPayload,
    EventType.TX_CONFIRMED: TransactionPayload,
    EventType.TX_FAILED: TransactionPayload,
}


class UnknownEventType(ValueError):
    pass


def validate_payload(event_type: str, payload: dict[str, object]) -> dict[str, object]:
    schema = PAYLOAD_SCHEMAS.get(event_type)
    if schema is None:
        raise UnknownEventType(f"No schema registered for event type {event_type!r}")
    return schema.model_validate(payload).model_dump(mode="json")
