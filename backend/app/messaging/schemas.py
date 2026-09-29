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


class DataExportPayload(UserPayload):
    export_id: uuid.UUID
    expires_at: str


class AccountDeletionPayload(UserPayload):
    request_id: uuid.UUID
    scheduled_for: str


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


class TrustlinePayload(_Payload):
    bounty_id: uuid.UUID
    requester_id: uuid.UUID
    contributor_id: uuid.UUID
    title: str
    asset_code: str
    asset: str
    stage: str  # assignment | payout


class TransactionPayload(_Payload):
    transaction_id: uuid.UUID
    bounty_id: uuid.UUID | None = None
    transaction_type: str
    status: str


class NotificationPayload(_Payload):
    notification_id: uuid.UUID
    user_id: uuid.UUID
    notification_type: str


class QAPayload(_Payload):
    """Bounty Q&A. ``participant_ids`` are the other people in the thread (for reply notifications)."""

    bounty_id: uuid.UUID
    requester_id: uuid.UUID
    title: str
    post_id: uuid.UUID
    question_id: uuid.UUID
    author_id: uuid.UUID
    asker_id: uuid.UUID
    participant_ids: list[uuid.UUID] = []


class GitHubAccountPayload(UserPayload):
    github_id: int
    login: str


class PullRequestPayload(SubmissionPayload):
    pull_request_id: uuid.UUID
    repository: str
    number: int
    state: str | None = None
    previous_state: str | None = None
    verification: str


class AttestationPayload(_Payload):
    """An on-chain completion attestation (``onchain_id`` is the attestation contract's id)."""

    attestation_id: uuid.UUID
    bounty_id: uuid.UUID
    contributor_id: uuid.UUID
    title: str
    amount: str
    onchain_id: int
    status: str


class SavedSearchAlertPayload(UserPayload):
    """An instant saved-search alert email: one bounty, the recipient's searches it matched."""

    bounty_id: uuid.UUID
    saved_search_ids: list[uuid.UUID]


class SavedSearchDigestSection(BaseModel):
    saved_search_id: uuid.UUID
    bounty_ids: list[uuid.UUID]


class SavedSearchDigestPayload(UserPayload):
    frequency: str  # DAILY | WEEKLY
    sections: list[SavedSearchDigestSection]


PAYLOAD_SCHEMAS: dict[str, type[_Payload]] = {
    EventType.USER_REGISTERED: UserPayload,
    EventType.USER_EMAIL_VERIFIED: UserPayload,
    EventType.WALLET_VERIFIED: UserPayload,
    EventType.WALLET_PASSKEY_CREATED: UserPayload,
    EventType.EMAIL_VERIFICATION_REQUESTED: UserPayload,
    EventType.PASSWORD_RESET_REQUESTED: UserPayload,
    EventType.DATA_EXPORT_READY: DataExportPayload,
    EventType.ACCOUNT_DELETION_REQUESTED: AccountDeletionPayload,
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
    EventType.ASSET_TRUSTLINE_REQUIRED: TrustlinePayload,
    EventType.TX_SUBMITTED: TransactionPayload,
    EventType.TX_CONFIRMED: TransactionPayload,
    EventType.TX_FAILED: TransactionPayload,
    EventType.QA_QUESTION_CREATED: QAPayload,
    EventType.QA_REPLY_CREATED: QAPayload,
    EventType.QA_REPLY_ACCEPTED: QAPayload,
    EventType.QA_POST_HIDDEN: QAPayload,
    EventType.GITHUB_ACCOUNT_LINKED: GitHubAccountPayload,
    EventType.GITHUB_ACCOUNT_UNLINKED: GitHubAccountPayload,
    EventType.SUBMISSION_PULL_REQUEST_UPDATED: PullRequestPayload,
    EventType.ATTESTATION_CONFIRMED: AttestationPayload,
    EventType.ATTESTATION_REVOKED: AttestationPayload,
    EventType.SAVED_SEARCH_ALERT: SavedSearchAlertPayload,
    EventType.SAVED_SEARCH_DIGEST: SavedSearchDigestPayload,
}


class OnchainSubmissionPayload(SubmissionPayload):
    claimable_at: str | None = None


class MilestonePaymentPayload(PaymentPayload):
    milestone_id: uuid.UUID
    milestone_title: str


class DisputeVotePayload(DisputePayload):
    approvals: int
    threshold: int


_ESCROW_V2_SCHEMAS: dict[str, type[_Payload]] = {
    EventType.SUBMISSION_ONCHAIN_RECORDED: OnchainSubmissionPayload,
    EventType.SUBMISSION_CLAIM_AVAILABLE: OnchainSubmissionPayload,
    EventType.MILESTONE_PAID: MilestonePaymentPayload,
    EventType.DISPUTE_VOTE_RECORDED: DisputeVotePayload,
}
PAYLOAD_SCHEMAS.update(_ESCROW_V2_SCHEMAS)


class UnknownEventType(ValueError):
    pass


def validate_payload(event_type: str, payload: dict[str, object]) -> dict[str, object]:
    schema = PAYLOAD_SCHEMAS.get(event_type)
    if schema is None:
        raise UnknownEventType(f"No schema registered for event type {event_type!r}")
    return schema.model_validate(payload).model_dump(mode="json")
