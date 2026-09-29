"""Account deletion (the right to erasure), with the records the law requires kept pseudonymised.

1. The user asks, re-entering their password. Nothing may be in flight: no escrow holding their funds, no open
   dispute they are party to, no work or payout still owed to them, no transaction awaiting confirmation.
2. The request waits out a grace period (``ACCOUNT_DELETION_GRACE_DAYS``) and can be cancelled until then. An
   email confirms the date.
3. The worker's ``account-deletion`` job then checks the blockers again and anonymises the account. If
   something opened in the meantime, it records why and tries again on its next run.

Anonymisation erases identity and content: email, name, username, profile, skills, sessions, tokens,
notifications, bookmarks, application texts, unpaid submission texts and exports. It keeps, linked to a
pseudonymous identity, what financial, tax and anti-money-laundering record keeping needs: bounties, escrows,
payment records, blockchain transactions (public on Stellar anyway), wallet addresses, approved work, disputes and
the audit log. The user row itself stays, so every foreign key keeps pointing at the pseudonym.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.invalidation import invalidate_profile
from app.cache.redis import cache_delete
from app.core.config import get_settings
from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.money import ZERO
from app.core.schemas import Page, PageParams, UserSummary
from app.core.security import utcnow, verify_password_async
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.applications.models import (
    ApplicationStatus,
    AssignmentStatus,
    BountyApplication,
    BountyAssignment,
)
from app.modules.auth.models import EmailVerificationToken, PasswordResetToken, UserSession
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty, BountyBookmark, BountyStatus
from app.modules.compliance import registry
from app.modules.compliance.models import AccountDeletionRequest, DataExport, DeletionStatus
from app.modules.compliance.registry import Blocker
from app.modules.compliance.schemas import (
    AdminDeletionRequestOut,
    BlockerOut,
    DeletionRequestOut,
    DeletionStatusOut,
)
from app.modules.credentials.service import STATUS_LIST_KEY as CREDENTIAL_STATUS_LIST_KEY
from app.modules.disputes.models import Dispute, DisputeStatus
from app.modules.notifications.models import EmailDelivery, Notification, NotificationPreference
from app.modules.payments.models import (
    BlockchainTransaction,
    BountyEscrow,
    EscrowState,
    PaymentRecord,
    PaymentStatus,
    TxStatus,
)
from app.modules.submissions.models import BountySubmission, SubmissionRevision, SubmissionStatus
from app.modules.users.models import User, UserSkill, Wallet, WalletVerificationStatus

logger = get_logger(__name__)

REMOVED = "[removed at the account holder's request]"
DELETED_NAME = "Deleted user"
DELETED_EMAIL_DOMAIN = "deleted.invalid"
PRIVACY_LINK = "/app/privacy"

# Bounty states with live money or work that the requester must settle first.
_REQUESTER_ACTIVE = (
    BountyStatus.FUNDING_PENDING,
    BountyStatus.FUNDED,
    BountyStatus.IN_PROGRESS,
    BountyStatus.UNDER_REVIEW,
    BountyStatus.CANCEL_REQUESTED,
    BountyStatus.DISPUTED,
)
_HELD = (EscrowState.AWAITING_FUNDING, EscrowState.FUNDED, EscrowState.CANCEL_REQUESTED, EscrowState.DISPUTED)
_OPEN_DISPUTES = (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW)
_UNSETTLED_PAYMENTS = (PaymentStatus.CREATED, PaymentStatus.SIGNATURE_REQUIRED, PaymentStatus.SUBMITTED)


def pseudonym_for(user_id: uuid.UUID) -> str:
    return "deleted-" + hashlib.sha256(f"bountyflow:user:{user_id}".encode()).hexdigest()[:12]


# --- Blockers --------------------------------------------------------------------------------


async def _count(session: AsyncSession, stmt: Any) -> int:
    return int(await session.scalar(stmt) or 0)


async def blockers(session: AsyncSession, user_id: uuid.UUID) -> list[Blocker]:
    found: list[Blocker] = []
    funded = (
        await session.scalars(
            select(Bounty.id)
            .join(BountyEscrow, BountyEscrow.bounty_id == Bounty.id)
            .where(
                Bounty.requester_id == user_id,
                BountyEscrow.state.in_(_HELD),
                BountyEscrow.funded_amount - BountyEscrow.paid_out_amount - BountyEscrow.refunded_amount
                > ZERO,
            )
        )
    ).all()
    if funded:
        found.append(
            Blocker(
                "funded_escrow",
                "Escrows you funded still hold money. Pay out or refund them first.",
                len(funded),
                [f"/app/bounties/{b}" for b in funded[:5]],
            )
        )
    in_progress = select(Bounty.id).where(
        Bounty.requester_id == user_id, Bounty.status.in_(_REQUESTER_ACTIVE)
    )
    if funded:
        in_progress = in_progress.where(Bounty.id.not_in(funded))
    active = (await session.scalars(in_progress)).all()
    if active:
        found.append(
            Blocker(
                "active_bounty",
                "Some of your bounties are still in progress. Complete or cancel them first.",
                len(active),
                [f"/app/bounties/{b}" for b in active[:5]],
            )
        )
    disputes = await _count(
        session,
        select(func.count(Dispute.id))
        .join(Bounty, Bounty.id == Dispute.bounty_id)
        .where(
            Dispute.status.in_(_OPEN_DISPUTES),
            or_(
                Dispute.raised_by_id == user_id,
                Dispute.contributor_id == user_id,
                Bounty.requester_id == user_id,
            ),
        ),
    )
    if disputes:
        found.append(Blocker("open_dispute", "You are part of an open dispute.", disputes))
    work = await _count(
        session,
        select(func.count(BountyAssignment.id))
        .join(Bounty, Bounty.id == BountyAssignment.bounty_id)
        .where(
            BountyAssignment.contributor_id == user_id,
            BountyAssignment.status == AssignmentStatus.ACTIVE,
            Bounty.status.not_in([BountyStatus.COMPLETED, BountyStatus.CANCELLED]),
        ),
    )
    if work:
        found.append(
            Blocker(
                "active_assignment",
                "You are assigned to bounties that are not finished yet.",
                work,
                ["/app/submissions"],
            )
        )
    owed = await _count(
        session,
        select(func.count(PaymentRecord.id)).where(
            PaymentRecord.contributor_id == user_id, PaymentRecord.payment_status.in_(_UNSETTLED_PAYMENTS)
        ),
    )
    if owed:
        found.append(
            Blocker("unsettled_payout", "A payout to you has not been settled yet.", owed, ["/app/payments"])
        )
    pending_tx = await _count(
        session,
        select(func.count(BlockchainTransaction.id)).where(
            BlockchainTransaction.user_id == user_id, BlockchainTransaction.status == TxStatus.SUBMITTED
        ),
    )
    if pending_tx:
        found.append(
            Blocker(
                "pending_transaction",
                "A transaction you submitted is still being confirmed.",
                pending_tx,
                ["/app/transactions"],
            )
        )
    registry.load_sections()
    for extra in registry.DELETION_BLOCKERS:
        found.extend(await extra(session, user_id))
    return found


def _blockers_out(items: list[Blocker]) -> list[BlockerOut]:
    return [BlockerOut(kind=b.kind, message=b.message, count=b.count, links=b.links) for b in items]


# --- User actions ----------------------------------------------------------------------------


async def _open_request(session: AsyncSession, user_id: uuid.UUID) -> AccountDeletionRequest | None:
    return await session.scalar(
        select(AccountDeletionRequest).where(
            AccountDeletionRequest.user_id == user_id,
            AccountDeletionRequest.status == DeletionStatus.SCHEDULED,
        )
    )


async def get_status(session: AsyncSession, user: User) -> DeletionStatusOut:
    request = await _open_request(session, user.id)
    return DeletionStatusOut(
        request=DeletionRequestOut.model_validate(request) if request else None,
        blockers=_blockers_out(await blockers(session, user.id)),
        grace_days=get_settings().account_deletion_grace_days,
    )


async def request_deletion(
    session: AsyncSession, user: User, password: str, reason: str | None
) -> DeletionStatusOut:
    if not await verify_password_async(user.password_hash, password):
        raise ValidationFailed(
            "The password is not correct.",
            code="invalid_password",
            details=[{"field": "password", "message": "Incorrect password"}],
        )
    if await _open_request(session, user.id) is not None:
        raise Conflict("Your account is already scheduled for deletion.")
    found = await blockers(session, user.id)
    if found:
        raise Conflict(
            "Your account can’t be deleted yet.",
            code="deletion_blocked",
            details=[b.model_dump() for b in _blockers_out(found)],
        )
    scheduled_for = utcnow() + timedelta(days=get_settings().account_deletion_grace_days)
    request = AccountDeletionRequest(
        user_id=user.id,
        status=DeletionStatus.SCHEDULED,
        reason=(reason or "").strip() or None,
        scheduled_for=scheduled_for,
    )
    session.add(request)
    await session.flush()
    audit.record(
        session,
        actor_id=user.id,
        action="privacy.deletion_requested",
        entity_type="user",
        entity_id=user.id,
        metadata={"request_id": str(request.id), "scheduled_for": scheduled_for.isoformat()},
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.ACCOUNT_DELETION_REQUESTED,
        aggregate_type="user",
        aggregate_id=user.id,
        actor_id=user.id,
        payload={"user_id": user.id, "request_id": request.id, "scheduled_for": scheduled_for.isoformat()},
    )
    await session.commit()
    logger.info("account_deletion_scheduled", user_id=str(user.id), scheduled_for=scheduled_for.isoformat())
    return await get_status(session, user)


async def cancel_deletion(session: AsyncSession, user: User) -> DeletionStatusOut:
    request = await _open_request(session, user.id)
    if request is None:
        raise NotFound("There is no scheduled deletion to cancel.")
    request.status = DeletionStatus.CANCELLED
    request.cancelled_at = utcnow()
    audit.record(
        session,
        actor_id=user.id,
        action="privacy.deletion_cancelled",
        entity_type="user",
        entity_id=user.id,
        metadata={"request_id": str(request.id)},
        is_public=False,
    )
    await session.commit()
    return await get_status(session, user)


# --- Anonymisation -------------------------------------------------------------------------


async def anonymise(session: AsyncSession, user: User) -> str:
    """Erases the account's identity and content in the caller's transaction. Returns the pseudonym."""
    uid = user.id
    now = utcnow()
    pseudonym = pseudonym_for(uid)
    placeholder_email = f"{pseudonym}@{DELETED_EMAIL_DOMAIN}"

    # Drafts and unfunded open bounties are closed through the lifecycle (applicants are told).
    closable = (
        await session.scalars(
            select(Bounty)
            .where(
                Bounty.requester_id == uid,
                Bounty.status.in_([BountyStatus.DRAFT, BountyStatus.OPEN, BountyStatus.EXPIRED]),
            )
            .with_for_update()
        )
    ).all()
    for bounty in closable:
        # The account holder is the actor, so the lifecycle does not notify the account being deleted.
        await bounty_service.finalize_cancellation(session, bounty, actor_id=uid)

    await session.execute(
        update(BountyApplication)
        .where(BountyApplication.contributor_id == uid, BountyApplication.status == ApplicationStatus.PENDING)
        .values(status=ApplicationStatus.WITHDRAWN)
    )
    await session.execute(
        update(BountyApplication)
        .where(BountyApplication.contributor_id == uid)
        .values(cover_message=REMOVED, relevant_experience=None, work_samples=[])
    )
    # Approved work was paid for: it stays with the bounty as the record of what was delivered.
    unpaid = select(BountySubmission.id).where(
        BountySubmission.contributor_id == uid, BountySubmission.status != SubmissionStatus.APPROVED
    )
    await session.execute(
        update(SubmissionRevision)
        .where(SubmissionRevision.submission_id.in_(unpaid))
        .values(description=REMOVED, evidence_url=None, evidence_links=[])
    )
    await session.execute(
        update(BountySubmission)
        .where(BountySubmission.contributor_id == uid, BountySubmission.status != SubmissionStatus.APPROVED)
        .values(description=REMOVED, evidence_url=None, evidence_links=[])
    )

    await session.execute(delete(UserSession).where(UserSession.user_id == uid))
    await session.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == uid))
    await session.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == uid))
    await session.execute(delete(Notification).where(Notification.user_id == uid))
    await session.execute(delete(BountyBookmark).where(BountyBookmark.user_id == uid))
    await session.execute(delete(NotificationPreference).where(NotificationPreference.user_id == uid))
    await session.execute(delete(UserSkill).where(UserSkill.user_id == uid))
    await session.execute(delete(DataExport).where(DataExport.user_id == uid))
    await session.execute(
        update(EmailDelivery).where(EmailDelivery.user_id == uid).values(to_address=placeholder_email)
    )
    # Addresses stay (payments and on-chain history reference them), but they are no longer linked for use.
    await session.execute(
        update(Wallet)
        .where(Wallet.user_id == uid, Wallet.verification_status == WalletVerificationStatus.VERIFIED)
        .values(
            verification_status=WalletVerificationStatus.REVOKED,
            revoked_at=now,
            verification_note="account deleted",
        )
    )

    registry.load_sections()
    for extra in registry.ANONYMISERS:
        await extra(session, user)

    user.email = placeholder_email
    user.normalized_email = placeholder_email
    user.password_hash = "!deleted:" + secrets.token_hex(16)  # not an Argon2 hash: no password matches it
    user.display_name = DELETED_NAME
    user.username = pseudonym
    user.avatar_url = None
    user.bio = None
    user.github_url = None
    user.portfolio_url = None
    user.interests = []
    user.email_verified_at = None
    user.wants_to_request = False
    user.wants_to_contribute = False
    user.is_active = False
    audit.record(
        session,
        actor_id=None,
        action="account.anonymised",
        entity_type="user",
        entity_id=uid,
        metadata={"pseudonym": pseudonym},
        is_public=False,
    )
    session.expire(user, ["skills"])
    return pseudonym


async def execute_next(session: AsyncSession) -> bool:
    """Runs one due deletion. Returns False when none is due."""
    request = await session.scalar(
        select(AccountDeletionRequest)
        .where(
            AccountDeletionRequest.status == DeletionStatus.SCHEDULED,
            AccountDeletionRequest.scheduled_for <= utcnow(),
            or_(
                AccountDeletionRequest.last_attempt_at.is_(None),
                AccountDeletionRequest.last_attempt_at < utcnow() - timedelta(hours=1),
            ),
        )
        .order_by(AccountDeletionRequest.scheduled_for)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if request is None:
        return False
    request.last_attempt_at = utcnow()
    found = await blockers(session, request.user_id)
    if found:
        request.blocked_reason = "; ".join(f"{b.message} ({b.count})" for b in found)[:1000]
        await session.commit()
        logger.info("account_deletion_blocked", request_id=str(request.id), blockers=[b.kind for b in found])
        return True
    user = await session.get(User, request.user_id, with_for_update=True)
    if user is None:  # pragma: no cover - user rows are never deleted
        request.status = DeletionStatus.CANCELLED
        await session.commit()
        return True
    old_username = user.username
    request.pseudonym = await anonymise(session, user)
    request.status = DeletionStatus.COMPLETED
    request.completed_at = utcnow()
    request.blocked_reason = None
    request.reason = None
    await session.commit()
    # Cache invalidation only after the commit: nothing here runs while the account's rows are locked.
    await invalidate_profile(old_username, request.pseudonym)
    await cache_delete(CREDENTIAL_STATUS_LIST_KEY)  # revoked credentials must show in the public status list
    logger.info("account_deleted", request_id=str(request.id))
    return True


# --- Staff -----------------------------------------------------------------------------------


async def list_requests(
    session: AsyncSession, status_filter: DeletionStatus | None, params: PageParams
) -> Page[AdminDeletionRequestOut]:
    base = select(AccountDeletionRequest, User).join(User, User.id == AccountDeletionRequest.user_id)
    if status_filter:
        base = base.where(AccountDeletionRequest.status == status_filter)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        await session.execute(
            base.order_by(
                AccountDeletionRequest.scheduled_for.asc(), AccountDeletionRequest.created_at.desc()
            )
            .offset(params.offset)
            .limit(params.page_size)
        )
    ).all()
    items: list[AdminDeletionRequestOut] = []
    for request, user in rows:
        live = await blockers(session, user.id) if request.status == DeletionStatus.SCHEDULED else []
        items.append(
            AdminDeletionRequestOut(
                **DeletionRequestOut.model_validate(request).model_dump(),
                user=UserSummary.model_validate(user),
                email=user.email,
                reason=request.reason,
                pseudonym=request.pseudonym,
                last_attempt_at=request.last_attempt_at,
                blockers=_blockers_out(live),
            )
        )
    return Page[AdminDeletionRequestOut].build(items, total, params)
