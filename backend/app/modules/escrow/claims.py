"""Worker side of the review clock: marks submissions whose on-chain review window passed unanswered and tells
both parties that the contributor can claim the payment.

The mark (``claim_notified_at``) only drives notifications and the UI; the contract decides whether a claim
succeeds when the contributor signs it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.invalidation import invalidate_bounty
from app.core.logging import get_logger
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.escrow import review_clock
from app.modules.payments.models import BountyEscrow
from app.modules.submissions.models import BountySubmission, OnchainReviewState

logger = get_logger(__name__)


async def mark_claimable(session: AsyncSession, limit: int = 100) -> int:
    now = utcnow()
    rows = (
        await session.execute(
            select(BountySubmission, Bounty, BountyEscrow)
            .join(Bounty, Bounty.id == BountySubmission.bounty_id)
            .join(BountyEscrow, BountyEscrow.bounty_id == Bounty.id)
            .where(
                BountySubmission.onchain_state == OnchainReviewState.PENDING,
                BountySubmission.claimable_at.is_not(None),
                BountySubmission.claimable_at <= now,
                BountySubmission.claim_notified_at.is_(None),
                Bounty.status != BountyStatus.DISPUTED,
            )
            .order_by(BountySubmission.claimable_at)
            .with_for_update(of=BountySubmission, skip_locked=True)
            .limit(limit)
        )
    ).all()
    marked: list[Bounty] = []
    for submission, bounty, escrow in rows:
        assert submission.claimable_at is not None
        # A dispute resolved after the submission gave the requester a full window again.
        opens_at = review_clock.effective_claimable_at(
            int(submission.claimable_at.timestamp()), escrow.clock_reset_at, escrow.review_window_seconds or 0
        )
        if escrow.state not in review_clock.REVIEW_OPEN:
            continue
        if opens_at > int(now.timestamp()):
            submission.claimable_at = review_clock.to_datetime(opens_at)
            continue
        submission.claim_notified_at = now
        add_event(
            session,
            event_type=EventType.SUBMISSION_CLAIM_AVAILABLE,
            aggregate_type="submission",
            aggregate_id=submission.id,
            payload={
                "submission_id": submission.id,
                "bounty_id": bounty.id,
                "requester_id": bounty.requester_id,
                "contributor_id": submission.contributor_id,
                "title": bounty.title,
                "status": submission.status.value,
                "version": submission.version,
                "claimable_at": submission.claimable_at.isoformat(),
            },
        )
        marked.append(bounty)
    await session.commit()
    for bounty in marked:
        await invalidate_bounty(str(bounty.id), bounty.slug)
    if marked:
        logger.info("claims_available", count=len(marked))
    return len(marked)
