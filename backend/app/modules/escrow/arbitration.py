"""The arbiter panel of a dispute: the escrow's M-of-N arbiter set, who approved what, and whether the viewer can
approve with one of their own arbiter wallets.

The contract is read live (``get_escrow`` and ``resolution_votes``). When the RPC cannot be reached the panel falls
back to the verified mirror (``dispute_votes`` and the escrow row) and says so.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.config import get_network
from app.blockchain.soroban import EscrowSnapshot
from app.blockchain.transactions import ChainUnavailable
from app.core.exceptions import NotFound
from app.core.logging import get_logger
from app.core.money import from_stroops
from app.core.rbac import Permission, has_permission
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.disputes.models import Dispute, DisputeResolution, DisputeStatus
from app.modules.escrow import chain as escrow_chain
from app.modules.escrow.models import DisputeVote
from app.modules.escrow.schemas import ArbiterOut, ArbitrationOut
from app.modules.payments.models import BountyEscrow, EscrowState
from app.modules.users.models import Role, User, Wallet, WalletVerificationStatus

logger = get_logger(__name__)

_DECISIONS = (
    DisputeResolution.RELEASE_TO_CONTRIBUTOR,
    DisputeResolution.REFUND_TO_REQUESTER,
    DisputeResolution.SPLIT,
)


async def _staff_by_address(session: AsyncSession, addresses: list[str]) -> dict[str, User]:
    rows = await session.execute(
        select(Wallet.public_address, User)
        .join(User, User.id == Wallet.user_id)
        .where(
            Wallet.public_address.in_(addresses),
            Wallet.network == get_network().network,
            Wallet.verification_status == WalletVerificationStatus.VERIFIED,
            User.role.in_([Role.MODERATOR, Role.ADMIN]),
        )
    )
    return {address: user for address, user in rows.all()}


def _open_value(snapshot: EscrowSnapshot | None, escrow: BountyEscrow) -> Decimal:
    if snapshot is not None:
        return from_stroops(snapshot.position_value())
    return escrow.reward_per_position


async def arbitration(session: AsyncSession, viewer: User, dispute_id: uuid.UUID) -> ArbitrationOut:
    dispute = await session.get(Dispute, dispute_id)
    if dispute is None:
        raise NotFound("Dispute not found.")
    bounty = await bounty_repo.get(session, dispute.bounty_id)
    assert bounty is not None
    party = viewer.id in (dispute.raised_by_id, dispute.contributor_id, bounty.requester_id)
    if not (party or has_permission(viewer, Permission.DISPUTE_VIEW_ALL)):
        raise NotFound("Dispute not found.")
    escrow = await bounty_repo.get_escrow(session, bounty.id)
    if escrow is None:
        raise NotFound("This bounty has no escrow.")

    snapshot: EscrowSnapshot | None = None
    live_votes = None
    if escrow.contract_version >= 2 and escrow.state != EscrowState.NOT_CREATED:
        try:
            snapshot, trusted = await escrow_chain._payments()._read_trusted_snapshot(session, escrow)
            if not trusted:
                snapshot = None
            elif snapshot is not None:
                live_votes = await escrow_chain.read_votes(escrow)
        except ChainUnavailable:
            logger.warning("arbitration_read_deferred", dispute_id=str(dispute.id))

    arbiters = list(snapshot.arbiter_set) if snapshot else list(escrow.arbiter_addresses or [])
    threshold = snapshot.threshold if snapshot else escrow.arbiter_threshold
    vote_round = snapshot.dispute_round if snapshot else escrow.dispute_round
    frozen = (snapshot.status == "Disputed") if snapshot else escrow.state == EscrowState.DISPUTED

    mirror = (
        await session.scalars(
            select(DisputeVote).where(DisputeVote.dispute_id == dispute.id, DisputeVote.round == vote_round)
        )
    ).all()
    # While frozen, the contract's current votes; once executed they are spent, so the verified mirror shows them.
    if live_votes is not None and frozen:
        approved = {v.arbiter: from_stroops(v.contributor_amount) for v in live_votes}
    else:
        approved = {v.arbiter_address: v.contributor_amount for v in mirror}

    decided = dispute.resolution in _DECISIONS
    open_value = _open_value(snapshot, escrow)
    contributor_amount: Decimal | None = None
    if decided and snapshot is not None:
        contributor_amount = from_stroops(escrow_chain.resolution_amount(dispute, snapshot))
    elif dispute.resolution == DisputeResolution.SPLIT:
        contributor_amount = dispute.contributor_amount
    elif dispute.resolution == DisputeResolution.REFUND_TO_REQUESTER:
        contributor_amount = Decimal(0)
    elif dispute.resolution == DisputeResolution.RELEASE_TO_CONTRIBUTOR:
        contributor_amount = open_value
    approvals = sum(
        1 for amount in approved.values() if contributor_amount is not None and amount == contributor_amount
    )
    executed = decided and not frozen and bool(mirror) and dispute.status == DisputeStatus.RESOLVED

    staff = await _staff_by_address(session, arbiters)
    mine = [address for address in arbiters if address in staff and staff[address].id == viewer.id]
    my_vote = any(address in approved for address in mine)
    reason: str | None = None
    if not has_permission(viewer, Permission.DISPUTE_RESOLVE):
        reason = "Only moderators vote on dispute resolutions."
    elif party:
        reason = "You are a party to this dispute."
    elif escrow.contract_version < 2:
        reason = "This escrow was created on the v1 contract; its single arbiter executes the decision."
    elif not frozen:
        reason = "The escrow is not frozen on-chain."
    elif not decided:
        reason = "Record a release, refund or split decision first."
    elif not mine:
        reason = "Verify one of this escrow's arbiter wallets on your account to vote."
    elif all(approved.get(address) == contributor_amount for address in mine):
        reason = "Your approval is recorded."
    requester_amount = open_value - contributor_amount if contributor_amount is not None else None
    return ArbitrationOut(
        dispute_id=dispute.id,
        contract_version=escrow.contract_version,
        escrow_frozen=frozen,
        executed=executed,
        round=vote_round,
        threshold=threshold,
        approvals=approvals,
        arbiters=[
            ArbiterOut(
                address=address,
                staff=bounty_service.user_summary(staff[address]) if address in staff else None,
                approved=address in approved and approved[address] == contributor_amount,
                contributor_amount=approved.get(address),
            )
            for address in arbiters
        ],
        resolution=dispute.resolution.value if dispute.resolution else None,
        contributor_amount=contributor_amount,
        requester_amount=requester_amount if requester_amount is None or requester_amount >= 0 else None,
        position_value=open_value,
        my_arbiter_wallets=mine,
        my_vote_recorded=my_vote,
        can_vote=reason is None,
        vote_blocked_reason=reason,
    )
