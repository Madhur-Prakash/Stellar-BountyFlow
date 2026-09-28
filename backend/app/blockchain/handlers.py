"""On-chain verification of submitted transactions (consumer ``blockchain-verifier``).

``verify_transaction`` is idempotent: it inspects the transaction on the network and applies the resulting
state change at most once. A transient RPC failure (``ChainUnavailable``) propagates so the worker retries
the event with backoff; a transaction that is still pending is picked up again by the reconciliation job.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.transactions import ChainUnavailable
from app.core.logging import get_logger
from app.messaging.events import EventEnvelope, EventType, Topics
from app.messaging.registry import on

logger = get_logger(__name__)

CONSUMER = "blockchain-verifier"
TOPICS = [Topics.BLOCKCHAIN]


@on(CONSUMER, TOPICS, EventType.TX_SUBMITTED)
async def handle_transaction_submitted(session: AsyncSession, envelope: EventEnvelope) -> None:
    from app.modules.payments.service import verify_transaction

    transaction_id = uuid.UUID(str(envelope.payload["transaction_id"]))
    try:
        await verify_transaction(session, transaction_id)
    except ChainUnavailable:
        logger.warning("transaction_verification_deferred", transaction_id=str(transaction_id))
        raise
