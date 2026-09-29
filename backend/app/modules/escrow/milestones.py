"""Bounty milestones: authoring (draft bounties only) and the verified mirror of their on-chain payout state.

A milestone bounty has a single position; its milestone amounts add up to the reward, which is funded once. Each
approved milestone is released on its own (``release_milestone``). A milestone row only becomes PAID or SETTLED
from verified contract state, never from a client claim.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.config import get_network
from app.blockchain.soroban import EscrowSnapshot
from app.core.exceptions import Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.core.money import ZERO, display_amount, from_stroops
from app.core.security import utcnow
from app.modules.admin import audit
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.escrow.models import BountyMilestone, MilestoneStatus
from app.modules.escrow.schemas import MAX_MILESTONES, MIN_MILESTONES, MilestoneInput, MilestoneOut
from app.modules.payments.models import BlockchainTransaction, EscrowState, TxType
from app.modules.users.models import User


def serialize(m: BountyMilestone, tx_hash: str | None = None) -> MilestoneOut:
    return MilestoneOut(
        id=m.id,
        position=m.position,
        title=m.title,
        description=m.description,
        amount=m.amount,
        status=m.status,
        paid_at=m.paid_at,
        payout_transaction_id=m.payout_transaction_id,
        explorer_url=get_network().tx_url(tx_hash) if tx_hash else None,
    )


async def for_bounty(
    session: AsyncSession, bounty_id: uuid.UUID, *, for_update: bool = False
) -> list[BountyMilestone]:
    stmt = (
        select(BountyMilestone)
        .where(BountyMilestone.bounty_id == bounty_id)
        .order_by(BountyMilestone.position)
    )
    if for_update:  # the caller holds the bounty lock (lock order: bounty, then its milestones)
        await session.flush()  # a refresh under lock must not undo this transaction's unflushed changes
        stmt = stmt.with_for_update(of=BountyMilestone).execution_options(populate_existing=True)
    rows = await session.scalars(stmt)
    return list(rows.all())


async def serialized(session: AsyncSession, bounty_id: uuid.UUID) -> list[MilestoneOut]:
    rows = await for_bounty(session, bounty_id)
    tx_ids = [m.payout_transaction_id for m in rows if m.payout_transaction_id]
    hashes: dict[uuid.UUID, str | None] = {}
    if tx_ids:
        result = await session.execute(
            select(BlockchainTransaction.id, BlockchainTransaction.transaction_hash).where(
                BlockchainTransaction.id.in_(tx_ids)
            )
        )
        hashes = {tx_id: tx_hash for tx_id, tx_hash in result.all()}
    return [
        serialize(m, hashes.get(m.payout_transaction_id) if m.payout_transaction_id else None) for m in rows
    ]


def validate(
    inputs: Sequence[MilestoneInput], reward: Decimal, positions: int, asset_code: str = "XLM"
) -> None:
    """Milestones need one position and must add up to the reward exactly (the contract checks the same)."""
    if not inputs:
        return
    if positions != 1:
        raise ValidationFailed(
            "Milestones are for single-position bounties. Set positions to 1 or remove the milestones.",
            details=[{"field": "milestones", "message": "Needs a single position"}],
        )
    if not MIN_MILESTONES <= len(inputs) <= MAX_MILESTONES:
        raise ValidationFailed(
            f"Split the reward into {MIN_MILESTONES} to {MAX_MILESTONES} milestones.",
            details=[{"field": "milestones", "message": "Between 2 and 20 milestones"}],
        )
    total = sum((m.amount for m in inputs), ZERO)
    if total != reward:
        raise ValidationFailed(
            f"The milestones add up to {display_amount(total, asset_code)}, but the reward is "
            f"{display_amount(reward, asset_code)}.",
            details=[{"field": "milestones", "message": "Must add up to the reward"}],
        )


async def replace(session: AsyncSession, bounty: Bounty, inputs: Sequence[MilestoneInput]) -> None:
    """Replaces the milestones of a draft bounty. The caller commits."""
    validate(inputs, bounty.reward_amount, bounty.positions_available, bounty.reward_asset or "XLM")
    await session.execute(delete(BountyMilestone).where(BountyMilestone.bounty_id == bounty.id))
    await session.flush()
    for position, item in enumerate(inputs):
        session.add(
            BountyMilestone(
                id=uuid.uuid4(),
                bounty_id=bounty.id,
                position=position,
                title=item.title,
                description=(item.description or "").strip() or None,
                amount=item.amount,
                status=MilestoneStatus.OPEN,
            )
        )
    await session.flush()


async def update(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, inputs: Sequence[MilestoneInput]
) -> list[MilestoneOut]:
    bounty = await bounty_service.load_for_update(session, bounty_id)
    if bounty.requester_id != user.id:
        raise Forbidden("Only the bounty's requester can change its milestones.")
    escrow = await bounty_repo.get_escrow(session, bounty.id)
    if bounty.status != BountyStatus.DRAFT or (
        escrow is not None and escrow.state != EscrowState.NOT_CREATED
    ):
        raise InvalidStateTransition("Milestones can only be changed while the bounty is a draft.")
    await replace(session, bounty, inputs)
    audit.record(
        session,
        actor_id=user.id,
        action="bounty.milestones_updated",
        entity_type="bounty",
        entity_id=bounty.id,
        bounty_id=bounty.id,
        metadata={"count": len(inputs)},
        is_public=False,
    )
    await bounty_service.commit_bounty(session, bounty)
    return await serialized(session, bounty.id)


async def get(session: AsyncSession, bounty_id: uuid.UUID, viewer: User | None) -> list[MilestoneOut]:
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None or not bounty_service.can_view(bounty, viewer):
        raise NotFound("Bounty not found.")
    return await serialized(session, bounty.id)


async def sync_from_snapshot(
    session: AsyncSession,
    bounty_id: uuid.UUID,
    snapshot: EscrowSnapshot | None,
    tx: BlockchainTransaction | None,
) -> list[BountyMilestone]:
    """Marks milestones the (trusted) contract reports as paid. Returns the rows that changed.

    A milestone closed by a dispute resolution is SETTLED rather than PAID: the contributor may have received only
    part of it."""
    if snapshot is None or not snapshot.milestones:
        return []
    rows = await for_bounty(session, bounty_id, for_update=True)
    by_position = {m.position: m for m in rows}
    settled_by_dispute = tx is not None and tx.transaction_type in (
        TxType.DISPUTE_VOTE,
        TxType.DISPUTE_RESOLVE,
    )
    changed: list[BountyMilestone] = []
    now = utcnow()
    for position, (amount, paid) in enumerate(snapshot.milestones):
        row = by_position.get(position)
        if row is None or not paid or row.status != MilestoneStatus.OPEN:
            continue
        if from_stroops(amount) != row.amount:
            continue  # never mark a row whose terms differ from the escrow's
        row.status = MilestoneStatus.SETTLED if settled_by_dispute else MilestoneStatus.PAID
        row.paid_at = (tx.confirmed_at if tx else None) or now
        row.payout_transaction_id = tx.id if tx else None
        changed.append(row)
    return changed
