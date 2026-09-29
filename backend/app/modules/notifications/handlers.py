"""Domain events -> in-app notifications (consumer ``notification-worker``).

``build_notifications`` is a pure function that decides who is told what; the registered handler only
persists its output. The actor of an event is never notified about their own action.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.messaging.events import EventEnvelope, EventType, Topics
from app.messaging.registry import on
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import create_notification

logger = get_logger(__name__)

CONSUMER = "notification-worker"
TOPICS = [Topics.BOUNTY, Topics.APPLICATION, Topics.SUBMISSION, Topics.PAYMENT]


@dataclass(frozen=True)
class NotificationSpec:
    user_id: uuid.UUID
    notification_type: NotificationType
    title: str
    message: str
    link: str | None
    payload: dict[str, Any] = field(default_factory=dict)


# --- Frontend links -----------------------------------------------------------------


def public_bounty_link(bounty_id: Any) -> str:
    return f"/bounties/{bounty_id}"


def manage_bounty_link(bounty_id: Any) -> str:
    return f"/app/bounties/{bounty_id}"


def bounty_applications_link(bounty_id: Any) -> str:
    return f"/app/bounties/{bounty_id}/applications"


def bounty_submissions_link(bounty_id: Any) -> str:
    return f"/app/bounties/{bounty_id}/submissions"


MY_APPLICATIONS_LINK = "/app/applications"
MY_SUBMISSIONS_LINK = "/app/submissions"
MY_PAYMENTS_LINK = "/app/payments"
WALLET_ASSETS_LINK = "/app/profile#assets"


# --- Helpers ------------------------------------------------------------------------------


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _uuids(values: Any) -> list[uuid.UUID]:
    if not isinstance(values, list | tuple):
        return []
    return [u for u in (_uuid(v) for v in values) if u is not None]


def _quote(title: Any) -> str:
    return f"“{title}”"


def _amount(payload: dict[str, Any]) -> str:
    """Human amount, e.g. ``250.5 XLM`` (trailing zeros of the 7-decimal string trimmed)."""
    raw = str(payload.get("amount") or "0")
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    asset = payload.get("asset_code") or "XLM"
    return f"{raw} {asset}"


_PAYLOAD_KEYS = (
    "bounty_id",
    "application_id",
    "submission_id",
    "dispute_id",
    "transaction_id",
    "amount",
    "asset_code",
    "status",
    "version",
    "resolution",
)


def _context(envelope: EventEnvelope) -> dict[str, Any]:
    ctx = {k: envelope.payload[k] for k in _PAYLOAD_KEYS if k in envelope.payload}
    ctx["event_type"] = envelope.event_type
    return ctx


Builder = Callable[[dict[str, Any]], Iterable[NotificationSpec | None]]
_BUILDERS: dict[str, Builder] = {}


def _builder(*event_types: str) -> Callable[[Builder], Builder]:
    def register(fn: Builder) -> Builder:
        for et in event_types:
            _BUILDERS[et] = fn
        return fn

    return register


def _spec(
    user_id: Any, notification_type: NotificationType, title: str, message: str, link: str | None
) -> NotificationSpec | None:
    uid = _uuid(user_id)
    if uid is None:
        return None
    return NotificationSpec(uid, notification_type, title, message, link)


# --- Bounty lifecycle ------------------------------------------------------------------


@_builder(EventType.BOUNTY_PUBLISHED)
def _bounty_published(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.BOUNTY_PUBLISHED,
        "Your bounty is live",
        f"{_quote(p['title'])} is now published on the marketplace. Fund the escrow so contributors can be "
        "accepted.",
        public_bounty_link(p["bounty_id"]),
    )


@_builder(EventType.BOUNTY_FUNDED)
def _bounty_funded(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.BOUNTY_FUNDED,
        "Escrow funded",
        f"The escrow for {_quote(p['title'])} is funded. You can now accept applicants.",
        manage_bounty_link(p["bounty_id"]),
    )


@_builder(EventType.BOUNTY_CANCEL_REQUESTED)
def _cancel_requested(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    for contributor in _uuids(p.get("contributor_ids")):
        yield _spec(
            contributor,
            NotificationType.BOUNTY_CANCELLED,
            "Cancellation requested",
            f"The requester asked to cancel {_quote(p['title'])}. Review the request before the escrow is "
            "refunded.",
            manage_bounty_link(p["bounty_id"]),
        )
    for applicant in _uuids(p.get("applicant_ids")):  # their pending applications were closed
        yield _spec(
            applicant,
            NotificationType.BOUNTY_CANCELLED,
            "Bounty cancelled",
            f"{_quote(p['title'])} was cancelled by the requester, so your application was closed.",
            MY_APPLICATIONS_LINK,
        )


@_builder(EventType.BOUNTY_CANCELLED)
def _bounty_cancelled(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.BOUNTY_CANCELLED,
        "Bounty cancelled",
        f"{_quote(p['title'])} has been cancelled.",
        manage_bounty_link(p["bounty_id"]),
    )
    for recipient in _uuids(p.get("contributor_ids")) + _uuids(p.get("applicant_ids")):
        yield _spec(
            recipient,
            NotificationType.BOUNTY_CANCELLED,
            "Bounty cancelled",
            f"{_quote(p['title'])} was cancelled by the requester.",
            public_bounty_link(p["bounty_id"]),
        )


@_builder(EventType.BOUNTY_EXPIRED)
def _bounty_expired(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.BOUNTY_EXPIRED,
        "Bounty expired",
        f"{_quote(p['title'])} passed its deadline and has expired. Any unassigned escrow can be refunded.",
        manage_bounty_link(p["bounty_id"]),
    )
    for recipient in _uuids(p.get("applicant_ids")):
        yield _spec(
            recipient,
            NotificationType.BOUNTY_EXPIRED,
            "Bounty expired",
            f"{_quote(p['title'])} expired before your application was reviewed.",
            MY_APPLICATIONS_LINK,
        )


@_builder(EventType.BOUNTY_COMPLETED)
def _bounty_completed(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.SYSTEM,
        "Bounty completed",
        f"All positions for {_quote(p['title'])} are complete and paid out.",
        manage_bounty_link(p["bounty_id"]),
    )


@_builder(EventType.BOUNTY_DEADLINE_APPROACHING)
def _deadline(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    kind = "application" if p.get("deadline_type") == "application" else "completion"
    yield _spec(
        p["requester_id"],
        NotificationType.SYSTEM,
        "Deadline approaching",
        f"The {kind} deadline for {_quote(p['title'])} is coming up soon.",
        manage_bounty_link(p["bounty_id"]),
    )
    for contributor in _uuids(p.get("contributor_ids")):
        yield _spec(
            contributor,
            NotificationType.SYSTEM,
            "Deadline approaching",
            f"The {kind} deadline for {_quote(p['title'])} is coming up soon. Make sure your work is submitted.",
            MY_SUBMISSIONS_LINK,
        )


# --- Disputes -----------------------------------------------------------------------------

_RESOLUTION_TEXT = {
    "RELEASE_TO_CONTRIBUTOR": "the escrowed reward is released to the contributor",
    "REFUND_TO_REQUESTER": "the escrowed reward is refunded to the requester",
    "DISMISSED": "the dispute was dismissed",
}


@_builder(EventType.DISPUTE_RAISED, EventType.DISPUTE_UPDATED, EventType.DISPUTE_RESOLVED)
def _dispute(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    event_type = p["__event_type"]
    if event_type == EventType.DISPUTE_RAISED:
        title = "Dispute opened"
        message = f"A dispute was opened on {_quote(p['title'])}. A moderator will review the evidence."
    elif event_type == EventType.DISPUTE_RESOLVED:
        title = "Dispute resolved"
        outcome = _RESOLUTION_TEXT.get(str(p.get("resolution") or ""), "a moderator recorded a decision")
        message = f"The dispute on {_quote(p['title'])} is resolved: {outcome}."
    else:
        title = "Dispute updated"
        message = f"There is an update on the dispute for {_quote(p['title'])}."
    for party in (p.get("requester_id"), p.get("contributor_id")):
        yield _spec(
            party, NotificationType.DISPUTE_UPDATE, title, message, manage_bounty_link(p["bounty_id"])
        )


# --- Applications ------------------------------------------------------------------------


@_builder(EventType.APPLICATION_CREATED)
def _application_created(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.APPLICATION_RECEIVED,
        "New application",
        f"Someone applied to {_quote(p['title'])}. Review their application.",
        bounty_applications_link(p["bounty_id"]),
    )


@_builder(EventType.APPLICATION_ACCEPTED)
def _application_accepted(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.APPLICATION_ACCEPTED,
        "Application accepted",
        f"You were accepted for {_quote(p['title'])}. You can start working and submit when ready.",
        MY_APPLICATIONS_LINK,
    )


@_builder(EventType.APPLICATION_REJECTED)
def _application_rejected(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.APPLICATION_REJECTED,
        "Application not selected",
        f"Your application for {_quote(p['title'])} was not selected this time.",
        MY_APPLICATIONS_LINK,
    )


@_builder(EventType.APPLICATION_WITHDRAWN)
def _application_withdrawn(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.SYSTEM,
        "Application withdrawn",
        f"An applicant withdrew from {_quote(p['title'])}.",
        bounty_applications_link(p["bounty_id"]),
    )


# --- Submissions -------------------------------------------------------------------------


@_builder(EventType.SUBMISSION_CREATED, EventType.SUBMISSION_RESUBMITTED)
def _submission_received(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    resubmitted = p["__event_type"] == EventType.SUBMISSION_RESUBMITTED
    yield _spec(
        p["requester_id"],
        NotificationType.SUBMISSION_RECEIVED,
        "Revised submission received" if resubmitted else "New submission",
        (
            f"A revised submission (version {p.get('version')}) for {_quote(p['title'])} is ready for review."
            if resubmitted
            else f"Work was submitted for {_quote(p['title'])}. Review it and approve or request changes."
        ),
        bounty_submissions_link(p["bounty_id"]),
    )


@_builder(EventType.SUBMISSION_REVISION_REQUESTED)
def _revision_requested(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.REVISION_REQUESTED,
        "Revision requested",
        f"The requester asked for changes to your submission for {_quote(p['title'])}.",
        MY_SUBMISSIONS_LINK,
    )


@_builder(EventType.SUBMISSION_APPROVED)
def _submission_approved(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.SUBMISSION_APPROVED,
        "Submission approved",
        f"Your submission for {_quote(p['title'])} was approved. The payout will be released from escrow.",
        MY_SUBMISSIONS_LINK,
    )


@_builder(EventType.SUBMISSION_REJECTED)
def _submission_rejected(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.SUBMISSION_REJECTED,
        "Submission rejected",
        f"Your submission for {_quote(p['title'])} was rejected. See the reviewer's feedback for details.",
        MY_SUBMISSIONS_LINK,
    )


# --- Payments -------------------------------------------------------------------------------


@_builder(EventType.PAYMENT_CONFIRMED)
def _payment_confirmed(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    amount = _amount(p)
    yield _spec(
        p.get("contributor_id"),
        NotificationType.PAYMENT_CONFIRMED,
        "Payment received",
        f"You received {amount} for {_quote(p['title'])}.",
        MY_PAYMENTS_LINK,
    )
    yield _spec(
        p["requester_id"],
        NotificationType.PAYMENT_CONFIRMED,
        "Payout confirmed",
        f"The {amount} payout for {_quote(p['title'])} is confirmed.",
        MY_PAYMENTS_LINK,
    )


@_builder(EventType.PAYMENT_FAILED)
def _payment_failed(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.SYSTEM,
        "Payout failed",
        f"The {_amount(p)} payout for {_quote(p['title'])} failed. No funds left the escrow; you can "
        "retry it.",
        bounty_submissions_link(p["bounty_id"]),
    )


@_builder(EventType.REFUND_CONFIRMED)
def _refund_confirmed(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.PAYMENT_CONFIRMED,
        "Refund confirmed",
        f"{_amount(p)} from the escrow of {_quote(p['title'])} was refunded to your wallet.",
        MY_PAYMENTS_LINK,
    )


@_builder(EventType.ASSET_TRUSTLINE_REQUIRED)
def _trustline_required(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    code = p.get("asset_code") or "the reward asset"
    step = "be paid" if p.get("stage") == "payout" else "be selected"
    yield _spec(
        p["contributor_id"],
        NotificationType.SYSTEM,
        f"Add a {code} trustline",
        f"{_quote(p['title'])} pays in {code}. Add a {code} trustline to your wallet so you can {step}.",
        WALLET_ASSETS_LINK,
    )


# --- Bounty Q&A -------------------------------------------------------------------------------------


def _qa_link(p: dict[str, Any]) -> str:
    return str(p.get("link") or public_bounty_link(p["bounty_id"]))


@_builder(EventType.QA_QUESTION_CREATED)
def _question_created(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.QUESTION_RECEIVED,
        "New question",
        f"Someone asked a question about {_quote(p['title'])}.",
        _qa_link(p),
    )


@_builder(EventType.QA_REPLY_CREATED)
def _reply_created(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    by_requester = bool(p.get("is_requester_answer"))
    for recipient in [p.get("asker_id"), *_uuids(p.get("participant_ids"))]:
        yield _spec(
            recipient,
            NotificationType.QUESTION_REPLY,
            "The requester answered" if by_requester else "New reply",
            (
                f"The requester replied in a question thread on {_quote(p['title'])}."
                if by_requester
                else f"There is a new reply in a question thread on {_quote(p['title'])}."
            ),
            _qa_link(p),
        )


@_builder(EventType.QA_REPLY_ACCEPTED)
def _reply_accepted(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p.get("author_id"),
        NotificationType.ANSWER_ACCEPTED,
        "Your answer was accepted",
        f"The requester accepted your reply as the answer on {_quote(p['title'])}.",
        _qa_link(p),
    )
    yield _spec(
        p.get("asker_id"),
        NotificationType.ANSWER_ACCEPTED,
        "Your question has an answer",
        f"The requester accepted an answer to your question on {_quote(p['title'])}.",
        _qa_link(p),
    )


@_builder(EventType.QA_POST_HIDDEN)
def _post_hidden(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p.get("author_id"),
        NotificationType.SYSTEM,
        "Your post was hidden",
        f"A moderator hid your post on {_quote(p['title'])}.",
        _qa_link(p),
    )


# --- GitHub pull requests ---------------------------------------------------------------------------


@_builder(EventType.SUBMISSION_PULL_REQUEST_UPDATED)
def _pull_request_updated(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    label = f"{p.get('repository')}#{p.get('number')}"
    if p.get("state") == "MERGED":
        yield _spec(
            p["requester_id"],
            NotificationType.PULL_REQUEST_UPDATE,
            "Pull request merged",
            f"{label}, linked to a submission for {_quote(p['title'])}, was merged.",
            bounty_submissions_link(p["bounty_id"]),
        )
        yield _spec(
            p["contributor_id"],
            NotificationType.PULL_REQUEST_UPDATE,
            "Pull request merged",
            f"Your pull request {label} for {_quote(p['title'])} was merged.",
            MY_SUBMISSIONS_LINK,
        )
    elif p.get("state") == "CLOSED":
        yield _spec(
            p["contributor_id"],
            NotificationType.PULL_REQUEST_UPDATE,
            "Pull request closed",
            f"Your pull request {label} for {_quote(p['title'])} was closed without being merged.",
            MY_SUBMISSIONS_LINK,
        )
        yield _spec(
            p["requester_id"],
            NotificationType.PULL_REQUEST_UPDATE,
            "Pull request closed",
            f"{label}, linked to a submission for {_quote(p['title'])}, was closed without being merged.",
            bounty_submissions_link(p["bounty_id"]),
        )


# --- On-chain attestations ------------------------------------------------------------------

MY_REPUTATION_LINK = "/app/profile#reputation"


@_builder(EventType.ATTESTATION_CONFIRMED)
def _attestation_confirmed(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.SYSTEM,
        "Completion recorded on-chain",
        f"Your completion of {_quote(p['title'])} is now attested on-chain. You can download a credential for it.",
        MY_REPUTATION_LINK,
    )


@_builder(EventType.ATTESTATION_REVOKED)
def _attestation_revoked(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.SYSTEM,
        "Attestation revoked",
        f"The on-chain attestation of your completion of {_quote(p['title'])} was revoked.",
        MY_REPUTATION_LINK,
    )


# --- Escrow v2: review clock, milestones and arbiter approvals -------------------------------------


def _when(value: Any) -> str:
    """``2026-10-06T12:00:00+00:00`` -> ``6 Oct 2026, 12:00 UTC``."""
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return "the end of the review window"
    return f"{moment.day} {moment:%b %Y, %H:%M} UTC"


@_builder(EventType.SUBMISSION_ONCHAIN_RECORDED)
def _submission_onchain(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["requester_id"],
        NotificationType.SUBMISSION_RECEIVED,
        "Review window started",
        f"Work for {_quote(p['title'])} is recorded on-chain. Answer it before {_when(p.get('claimable_at'))}, "
        "or the contributor can claim the payment.",
        bounty_submissions_link(p["bounty_id"]),
    )


@_builder(EventType.SUBMISSION_CLAIM_AVAILABLE)
def _claim_available(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    yield _spec(
        p["contributor_id"],
        NotificationType.CLAIM_AVAILABLE,
        "Payment ready to claim",
        f"The review window for your work on {_quote(p['title'])} passed without an answer. You can claim the "
        "payment now.",
        MY_SUBMISSIONS_LINK,
    )
    yield _spec(
        p["requester_id"],
        NotificationType.CLAIM_AVAILABLE,
        "Review window passed",
        f"The review window for work on {_quote(p['title'])} passed. The contributor can now claim the payment; "
        "you can still pay it yourself.",
        bounty_submissions_link(p["bounty_id"]),
    )


@_builder(EventType.MILESTONE_PAID)
def _milestone_paid(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    amount = _amount(p)
    milestone = _quote(p.get("milestone_title"))
    yield _spec(
        p.get("contributor_id"),
        NotificationType.MILESTONE_PAID,
        "Milestone paid",
        f"You received {amount} for the milestone {milestone} of {_quote(p['title'])}.",
        MY_PAYMENTS_LINK,
    )
    yield _spec(
        p["requester_id"],
        NotificationType.MILESTONE_PAID,
        "Milestone payout confirmed",
        f"The {amount} payout for the milestone {milestone} of {_quote(p['title'])} is confirmed.",
        bounty_submissions_link(p["bounty_id"]),
    )


@_builder(EventType.DISPUTE_VOTE_RECORDED)
def _dispute_vote(p: dict[str, Any]) -> Iterable[NotificationSpec | None]:
    approvals, threshold = int(p.get("approvals") or 0), int(p.get("threshold") or 1)
    if approvals >= threshold:
        title = "Dispute decision executed"
        message = f"The arbiters' decision on {_quote(p['title'])} was executed on-chain."
    else:
        title = "Arbiter approval recorded"
        message = f"{approvals} of {threshold} arbiter approvals are recorded for the dispute on {_quote(p['title'])}."
    for party in (p.get("requester_id"), p.get("contributor_id")):
        yield _spec(party, NotificationType.ARBITER_VOTE, title, message, manage_bounty_link(p["bounty_id"]))


HANDLED_EVENT_TYPES: tuple[str, ...] = tuple(_BUILDERS)


def build_notifications(envelope: EventEnvelope) -> list[NotificationSpec]:
    """Pure mapping from one domain event to notification specs, deduplicated per recipient and excluding
    the actor. Unknown event types produce nothing."""
    builder = _BUILDERS.get(envelope.event_type)
    if builder is None:
        return []
    payload = {**envelope.payload, "__event_type": envelope.event_type}
    context = _context(envelope)
    seen: set[uuid.UUID] = set()
    result: list[NotificationSpec] = []
    for spec in builder(payload):
        if spec is None or spec.user_id in seen:
            continue
        if envelope.actor_id is not None and spec.user_id == envelope.actor_id:
            continue
        seen.add(spec.user_id)
        result.append(
            NotificationSpec(
                spec.user_id, spec.notification_type, spec.title, spec.message, spec.link, context
            )
        )
    return result


@on(CONSUMER, TOPICS, *HANDLED_EVENT_TYPES)
async def handle_domain_event(session: AsyncSession, envelope: EventEnvelope) -> None:
    created = 0
    for spec in build_notifications(envelope):
        notification = await create_notification(
            session,
            user_id=spec.user_id,
            notification_type=spec.notification_type,
            title=spec.title,
            message=spec.message,
            link=spec.link,
            payload=spec.payload,
            source_event_id=envelope.event_id,
        )
        created += notification is not None
    if created:
        logger.info("notifications_created", event_type=envelope.event_type, count=created)
