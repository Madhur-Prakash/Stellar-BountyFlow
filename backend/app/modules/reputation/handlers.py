"""Verified payments -> queued completion attestations (consumer ``reputation-attester``).

Both payment events are emitted only after the escrow contract reported the payment on-chain, and either can be
the one that completes a contributor's position: ``payment.confirmed`` for a release, a batch leg, a claim or a
paying dispute resolution, ``payment.milestone_confirmed`` for a milestone payout (the last milestone completes
the position). ``enqueue`` itself checks that the position is fully paid, so both handlers are the same call.

The queue row is written in the same transaction as the processed-event marker, and is idempotent: one row per
(bounty, contributor). The ``attestation-pipeline`` job then signs, submits and verifies it on-chain.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.messaging.events import EventEnvelope, EventType, Topics
from app.messaging.registry import on
from app.modules.reputation.service import enqueue

logger = get_logger(__name__)

CONSUMER = "reputation-attester"
TOPICS = [Topics.PAYMENT]


@on(CONSUMER, TOPICS, EventType.PAYMENT_CONFIRMED, EventType.MILESTONE_PAID)
async def handle_payment_confirmed(session: AsyncSession, envelope: EventEnvelope) -> None:
    payload = envelope.payload
    contributor_id = payload.get("contributor_id")
    if not contributor_id:
        return
    row = await enqueue(
        session,
        transaction_id=uuid.UUID(str(payload["transaction_id"])),
        contributor_id=uuid.UUID(str(contributor_id)),
    )
    if row is not None:
        logger.info(
            "attestation_queued",
            attestation_id=str(row.id),
            status=row.status.value,
            payments=row.payments_count,
        )
