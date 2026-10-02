"""On-chain funding, assignment, payout, cancellation, refund and dispute actions.

Every action follows the same verifiable lifecycle:

1. ``prepare_action`` validates the domain rules and the caller's verified wallet, builds the Soroban invocation
   with that wallet as the source account, simulates it (surfacing contract errors before signing), and records a
   ``blockchain_transactions`` row in SIGNATURE_REQUIRED with the transaction hash.
2. The browser wallet signs the unmodified transaction.
3. ``submit_transaction`` verifies the signed envelope is exactly what we prepared and was signed by that wallet,
   submits it, and marks it SUBMITTED. Submission is *not* success.
4. ``verify_transaction`` (worker, sweep job, or a client poll) asks the network for the outcome. Only a
   confirmed SUCCESS is followed by reading the escrow state back from the contract and reconciling the database —
   funding, payouts and refunds are recorded from verified chain state, never from client claims.

Idempotency: transaction rows are unique per (network, hash); submission and verification are guarded by a Redis
lock per transaction; payment records are unique per submission and per (bounty, contributor); and the contract
itself rejects duplicate payouts (AlreadyPaid).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain import soroban, sponsorship
from app.blockchain.config import get_network
from app.blockchain.reconciliation import apply_snapshot, matches_prepared_creation
from app.blockchain.soroban import ContractCall, ContractError, EscrowSnapshot
from app.blockchain.transactions import (
    AccountNotFound,
    ChainRejected,
    ChainUnavailable,
    PreparedCall,
    get_adapter,
)
from app.blockchain.verification import EnvelopeMismatch
from app.cache import keys
from app.cache.invalidation import invalidate_bounty, invalidate_profile, invalidate_public_stats
from app.cache.redis import get_redis
from app.core.exceptions import (
    BlockchainError,
    Conflict,
    Forbidden,
    InvalidStateTransition,
    NotFound,
    ServiceUnavailable,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.money import ZERO, display_amount, fmt, parse_amount, to_stroops
from app.core.rbac import Permission, has_permission
from app.core.schemas import Page, PageParams, asset_from_identifier
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.assets import checks as asset_checks
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties import state_machine as sm
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.compliance import screening
from app.modules.disputes.models import Dispute, DisputeResolution, DisputeStatus
from app.modules.escrow import chain as escrow_chain
from app.modules.payments.models import (
    BlockchainTransaction,
    BountyEscrow,
    EscrowState,
    PaymentRecord,
    PaymentStatus,
    TxStatus,
    TxType,
)
from app.modules.payments.schemas import (
    BlockchainTransactionOut,
    ChainAction,
    FundingOut,
    PaymentRecordOut,
    PreparedTransactionOut,
    PrepareRequest,
    TxSummary,
    serialize_payment,
    serialize_tx,
)
from app.modules.submissions.models import BountySubmission, SubmissionStatus
from app.modules.users import repository as users_repo
from app.modules.users.models import User

logger = get_logger(__name__)

EXPIRY_GRACE = timedelta(seconds=90)
DEADLINE_GRACE = timedelta(days=7)
DEFAULT_ESCROW_DEADLINE = timedelta(days=60)


# --- Helpers ---------------------------------------------------------------------------


async def _get_or_create_escrow(session: AsyncSession, bounty: Bounty) -> BountyEscrow:
    escrow = await bounty_repo.get_escrow(session, bounty.id)
    if escrow is not None:
        return escrow
    network = get_network()
    # INSERT ... ON CONFLICT DO NOTHING: two concurrent first prepares (a double click) must not collide on the
    # unique bounty_id with an IntegrityError (500); the loser simply reads the row the winner created.
    await session.execute(
        pg_insert(BountyEscrow)
        .values(
            id=uuid.uuid4(),
            bounty_id=bounty.id,
            contract_id=network.contract_id,
            network=network.network,
            onchain_bounty_id=soroban.new_onchain_bounty_id(bounty.id).hex(),  # unpredictable (SEC-02)
            asset_identifier=bounty.reward_asset_identifier,
            asset_contract_id=network.sac_contract_id(bounty.reward_asset_identifier),
            reward_per_position=bounty.reward_amount,
            positions=bounty.positions_available,
            required_amount=bounty.total_reward,
            funded_amount=ZERO,
            paid_out_amount=ZERO,
            refunded_amount=ZERO,
            arbiter_address=network.arbiter_address,
            state=EscrowState.NOT_CREATED,
            **(await escrow_chain.new_row_values()),
        )
        .on_conflict_do_nothing()
    )
    escrow = await bounty_repo.get_escrow(session, bounty.id)
    assert escrow is not None
    return escrow


def _bid(escrow: BountyEscrow) -> bytes:
    return bytes.fromhex(escrow.onchain_bounty_id)


def _asset_code(escrow: BountyEscrow) -> str:
    return asset_from_identifier(escrow.asset_identifier).code


def _money(amount: Decimal | None, escrow: BountyEscrow) -> str:
    """Human amount in the escrow's asset, e.g. "150 XLM" or "25 USDC"."""
    return display_amount(amount, _asset_code(escrow))


async def _require_wallet(session: AsyncSession, user: User, address: str) -> str:
    network = get_network()
    wallet = await users_repo.find_verified_wallet(session, user.id, address, network.network)
    if wallet is None:
        raise Forbidden(
            "Connect and verify this wallet on your profile before using it for on-chain actions.",
            code="wallet_not_verified",
        )
    return wallet.public_address


async def _assigned_address(session: AsyncSession, assignment: BountyAssignment) -> str | None:
    """The contributor address recorded on-chain by a confirmed ASSIGN transaction, if any."""
    return await session.scalar(
        select(BlockchainTransaction.destination_address)
        .where(
            BlockchainTransaction.assignment_id == assignment.id,
            BlockchainTransaction.transaction_type == TxType.ASSIGN,
            BlockchainTransaction.status == TxStatus.CONFIRMED,
        )
        .order_by(BlockchainTransaction.confirmed_at.desc())
        .limit(1)
    )


async def _contributor_address(session: AsyncSession, assignment: BountyAssignment) -> str:
    locked = await _assigned_address(session, assignment) if assignment.onchain_assigned else None
    if locked:
        return locked
    wallet = await users_repo.primary_wallet(session, assignment.contributor_id, get_network().network)
    if wallet is None:
        raise ValidationFailed(
            "The contributor has no verified wallet to receive the reward.", code="contributor_wallet_missing"
        )
    return wallet.public_address


def _escrow_deadline(bounty: Bounty) -> int:
    now = datetime.now(UTC)
    target = (bounty.completion_deadline + DEADLINE_GRACE) if bounty.completion_deadline else None
    if target is None or target <= now + timedelta(hours=1):
        target = now + DEFAULT_ESCROW_DEADLINE
    return int(target.timestamp())


def _require_owner(bounty: Bounty, user: User) -> None:
    if bounty.requester_id != user.id:
        raise Forbidden("Only the bounty's requester can perform this action.")


def _require_requester_wallet(escrow: BountyEscrow, wallet: str) -> None:
    if escrow.requester_address and escrow.requester_address != wallet:
        raise ValidationFailed(
            f"This escrow was created by wallet {escrow.requester_address[:6]}…{escrow.requester_address[-4:]}. "
            "Sign with that wallet.",
            code="wrong_wallet",
        )


class _Plan:
    """What a prepared action will do on-chain, plus the DB links it settles."""

    def __init__(
        self,
        call: ContractCall,
        tx_type: TxType,
        description: str,
        *,
        amount: Decimal | None = None,
        destination: str | None = None,
        submission_id: uuid.UUID | None = None,
        assignment_id: uuid.UUID | None = None,
        dispute_id: uuid.UUID | None = None,
    ) -> None:
        self.call = call
        self.tx_type = tx_type
        self.description = description
        self.amount = amount
        self.destination = destination
        self.submission_id = submission_id
        self.assignment_id = assignment_id
        self.dispute_id = dispute_id
        self.metadata: dict[str, Any] = {}  # extra verification_metadata (escrow v2: batch legs, feedback)


async def _in_flight(session: AsyncSession, bounty_id: uuid.UUID, types: tuple[TxType, ...]) -> bool:
    count = await session.scalar(
        select(func.count(BlockchainTransaction.id)).where(
            BlockchainTransaction.bounty_id == bounty_id,
            BlockchainTransaction.transaction_type.in_(types),
            BlockchainTransaction.status == TxStatus.SUBMITTED,
        )
    )
    return bool(count)


_UNVERIFIED_ESCROW = (
    "The on-chain escrow at this bounty's escrow id was not created by BountyFlow with the expected terms "
    "(token, arbiter, reward, positions, deadline), so it cannot be used."
)


async def _escrow_is_authentic(session: AsyncSession, escrow: BountyEscrow, snapshot: EscrowSnapshot) -> bool:
    """SEC-01: an on-chain escrow is trusted only if its immutable terms equal a ``create_escrow`` that BountyFlow
    itself prepared for this bounty and escrow id (the contract lets anyone create any escrow at any id)."""
    prepared = (
        await session.execute(
            select(BlockchainTransaction.contract_id, BlockchainTransaction.verification_metadata).where(
                BlockchainTransaction.bounty_id == escrow.bounty_id,
                BlockchainTransaction.transaction_type == TxType.ESCROW_CREATE,
            )
        )
    ).all()
    # The creation must also have been prepared for the contract this escrow lives on (escrow v2: several
    # deployments hold escrows at the same time).
    return any(
        (contract_id is None or escrow.contract_id is None or contract_id == escrow.contract_id)
        and matches_prepared_creation(snapshot, escrow.onchain_bounty_id, (meta or {}).get("args") or {})
        for contract_id, meta in prepared
    )


async def _read_trusted_snapshot(
    session: AsyncSession, escrow: BountyEscrow
) -> tuple[EscrowSnapshot | None, bool]:
    """Reads the escrow from chain. Returns ``(snapshot, trusted)``; an untrusted (foreign) snapshot must never be
    applied to the database or used to settle anything."""
    snapshot = await get_adapter().read_escrow(_bid(escrow), escrow.contract_id)
    if snapshot is None:
        return None, True
    return snapshot, await _escrow_is_authentic(session, escrow, snapshot)


async def _sync_escrow_from_chain(session: AsyncSession, escrow: BountyEscrow) -> bool:
    """Refresh the DB escrow from chain before planning, so plans are built on authoritative state.
    Returns False, applying nothing, when a foreign escrow occupies the bounty's escrow id."""
    snapshot, trusted = await _read_trusted_snapshot(session, escrow)
    if not trusted:
        logger.warning(
            "foreign_escrow_detected",
            bounty_id=str(escrow.bounty_id),
            onchain_bounty_id=escrow.onchain_bounty_id,
        )
        return False
    apply_snapshot(escrow, snapshot)
    return True


async def _recover_from_foreign_escrow(
    session: AsyncSession, user: User, bounty: Bounty, escrow: BountyEscrow, action: ChainAction
) -> None:
    """SEC-01/SEC-02: a foreign escrow sits at this bounty's escrow id (squatted by a third party, or created
    directly by the requester with other terms, e.g. a worthless token). As long as BountyFlow has never observed
    its own escrow for the bounty, the requester's FUND simply moves the bounty to a fresh, unpredictable escrow id
    (squatting gains nothing). Every other action on such an escrow is refused."""
    can_move = (
        action == ChainAction.FUND
        and bounty.requester_id == user.id
        and escrow.state == EscrowState.NOT_CREATED
        and not await _in_flight(session, bounty.id, (TxType.ESCROW_CREATE, TxType.ESCROW_FUND))
    )
    if not can_move:
        raise Conflict(_UNVERIFIED_ESCROW, code="escrow_unverified")
    previous = escrow.onchain_bounty_id
    escrow.onchain_bounty_id = soroban.new_onchain_bounty_id(bounty.id).hex()
    logger.warning(
        "escrow_id_rotated", bounty_id=str(bounty.id), previous=previous, current=escrow.onchain_bounty_id
    )
    if not await _sync_escrow_from_chain(session, escrow):
        raise Conflict(_UNVERIFIED_ESCROW, code="escrow_unverified")


# --- Planning per action --------------------------------------------------------------------


async def _plan(session: AsyncSession, user: User, bounty: Bounty, req: PrepareRequest) -> _Plan:
    network = get_network()
    action = req.action

    if action == ChainAction.RESOLVE_DISPUTE:
        if not has_permission(user, Permission.DISPUTE_RESOLVE):
            raise Forbidden("Only moderators can execute dispute resolutions.")
        wallet = req.wallet_address
    else:
        wallet = await _require_wallet(session, user, req.wallet_address)

    escrow = await _get_or_create_escrow(session, bounty)
    if action == ChainAction.FUND:
        await escrow_chain.adopt_configured_contract(session, bounty, escrow)
    if not await _sync_escrow_from_chain(session, escrow):
        await _recover_from_foreign_escrow(session, user, bounty, escrow, action)
    bid = _bid(escrow)

    if action in escrow_chain.V2_ACTIONS:
        return await escrow_chain.plan(session, user, bounty, req, escrow, wallet)

    if action == ChainAction.FUND:
        _require_owner(bounty, user)
        if bounty.status not in (BountyStatus.OPEN, BountyStatus.FUNDING_PENDING):
            raise InvalidStateTransition("Only published, unfunded bounties can be funded.")
        if await _in_flight(session, bounty.id, (TxType.ESCROW_CREATE, TxType.ESCROW_FUND)):
            raise Conflict("A funding transaction is already being confirmed.")
        if not network.arbiter_address:
            raise ServiceUnavailable(
                "The dispute arbiter address is not configured (STELLAR_ARBITER_ADDRESS)."
            )
        if wallet == network.arbiter_address:
            raise ValidationFailed("The arbiter wallet cannot fund bounties.")
        required = bounty.total_reward
        if (
            escrow.state == EscrowState.NOT_CREATED
            and escrow.asset_identifier != bounty.reward_asset_identifier
        ):
            # Nothing exists on-chain yet, so the escrow simply follows the bounty's (draft-time) reward asset.
            escrow.asset_identifier = bounty.reward_asset_identifier
            escrow.asset_contract_id = network.sac_contract_id(bounty.reward_asset_identifier)
        if escrow.state == EscrowState.NOT_CREATED:
            deposit = parse_amount(req.amount) if req.amount else required
            if deposit > required:
                raise ValidationFailed("The deposit cannot exceed the total reward.")
            # create_escrow, or create_escrow_v2 for milestones, a review window or several arbiters.
            call = await escrow_chain.creation_call(
                session,
                bounty,
                escrow,
                requester=wallet,
                token=escrow.asset_contract_id or network.sac_contract_id(escrow.asset_identifier),
                reward_stroops=to_stroops(bounty.reward_amount),
                deadline=_escrow_deadline(bounty),
                deposit_stroops=to_stroops(deposit),
            )
            desc = f"Create the escrow and deposit {_money(deposit, escrow)} for “{bounty.title}”."
            return _Plan(call, TxType.ESCROW_CREATE, desc, amount=deposit, destination=network.contract_id)
        if escrow.state == EscrowState.AWAITING_FUNDING:
            _require_requester_wallet(escrow, wallet)
            remaining = escrow.required_amount - escrow.funded_amount
            amount = parse_amount(req.amount) if req.amount else remaining
            if amount > remaining:
                raise ValidationFailed(f"Only {_money(remaining, escrow)} remains to be funded.")
            call = soroban.fund(wallet, bid, to_stroops(amount))
            return _Plan(
                call,
                TxType.ESCROW_FUND,
                f"Deposit {_money(amount, escrow)} into the escrow.",
                amount=amount,
                destination=network.contract_id,
            )
        if escrow.state == EscrowState.FUNDED:
            # The escrow is verifiably funded on-chain but the bounty never left OPEN/FUNDING_PENDING (a funding
            # transaction the database lost track of). Reconcile the lifecycle instead of refusing forever.
            # Commit the escrow sync first: it holds the escrow row lock, and verification locks bounty -> escrow,
            # so taking the bounty lock while holding the escrow lock could deadlock.
            await session.commit()
            current = await bounty_repo.get(session, bounty.id, for_update=True)
            if current is not None and current.status in (BountyStatus.OPEN, BountyStatus.FUNDING_PENDING):
                bounty_service.change_status(
                    session,
                    current,
                    BountyStatus.FUNDED,
                    actor_id=None,
                    reason="reconciled with the on-chain escrow",
                    event_type=EventType.BOUNTY_FUNDED,
                )
                await session.commit()
                await invalidate_bounty(str(current.id), current.slug)
        raise Conflict("This bounty's escrow is already fully funded.")

    if action == ChainAction.ASSIGN:
        _require_owner(bounty, user)
        _require_requester_wallet(escrow, wallet)
        assignment = await session.get(BountyAssignment, req.assignment_id) if req.assignment_id else None
        if (
            assignment is None
            or assignment.bounty_id != bounty.id
            or assignment.status != AssignmentStatus.ACTIVE
        ):
            raise NotFound("Active assignment not found.")
        if assignment.onchain_assigned:
            raise Conflict("This contributor is already assigned on-chain.")
        if escrow.state != EscrowState.FUNDED:
            raise InvalidStateTransition(
                "The escrow must be fully funded before recording assignments on-chain."
            )
        if escrow.onchain_deadline is not None and escrow.onchain_deadline <= int(utcnow().timestamp()):
            # SEC-06: past the deadline the contract lets the requester refund despite assignments, so an
            # assignment recorded now would only give the contributor a false sense of protection.
            raise InvalidStateTransition(
                "The escrow deadline has passed, so an on-chain assignment would no longer protect the "
                "contributor's reward."
            )
        contributor = await _contributor_address(session, assignment)
        call = soroban.assign(wallet, bid, contributor)
        return _Plan(
            call,
            TxType.ASSIGN,
            "Record the contributor's assignment on-chain (protects their reward).",
            destination=contributor,
            assignment_id=assignment.id,
        )

    if action == ChainAction.PAYOUT:
        _require_owner(bounty, user)
        _require_requester_wallet(escrow, wallet)
        await escrow_chain.guard_payout(session, bounty)
        if bounty.status == BountyStatus.DISPUTED:
            raise InvalidStateTransition("Payouts are frozen while a dispute is open.")
        submission = await session.get(BountySubmission, req.submission_id) if req.submission_id else None
        if submission is None or submission.bounty_id != bounty.id:
            raise NotFound("Submission not found.")
        if submission.status != SubmissionStatus.APPROVED:
            raise InvalidStateTransition("Only approved submissions can be paid.")
        payment = await session.scalar(
            select(PaymentRecord).where(PaymentRecord.submission_id == submission.id)
        )
        if payment is None:
            raise NotFound("Payment record not found.")
        if payment.payment_status in (PaymentStatus.SUBMITTED, PaymentStatus.CONFIRMED):
            raise Conflict("This payout has already been submitted.")
        if escrow.state != EscrowState.FUNDED:
            raise InvalidStateTransition(
                "The escrow is not in a funded state, so the reward cannot be released."
            )
        assignment = await session.get(BountyAssignment, submission.assignment_id)
        assert assignment is not None
        contributor = await _contributor_address(session, assignment)
        call = soroban.release(wallet, bid, contributor)
        payment.payment_status = PaymentStatus.SIGNATURE_REQUIRED
        return _Plan(
            call,
            TxType.PAYOUT,
            f"Release {_money(bounty.reward_amount, escrow)} to the contributor.",
            amount=bounty.reward_amount,
            destination=contributor,
            submission_id=submission.id,
            assignment_id=assignment.id,
        )

    if action == ChainAction.REQUEST_CANCEL:
        _require_owner(bounty, user)
        _require_requester_wallet(escrow, wallet)
        if bounty.status not in (BountyStatus.CANCEL_REQUESTED, BountyStatus.EXPIRED):
            raise InvalidStateTransition("Request cancellation of the bounty first.")
        if escrow.state not in (EscrowState.AWAITING_FUNDING, EscrowState.FUNDED):
            raise InvalidStateTransition("The escrow is not in a cancellable state.")
        return _Plan(
            soroban.request_cancel(wallet, bid),
            TxType.CANCEL_REQUEST,
            "Request cancellation of the on-chain escrow.",
        )

    if action == ChainAction.CONSENT_CANCEL:
        assignment = await session.scalar(
            select(BountyAssignment).where(
                BountyAssignment.bounty_id == bounty.id,
                BountyAssignment.contributor_id == user.id,
                BountyAssignment.status == AssignmentStatus.ACTIVE,
                BountyAssignment.onchain_assigned.is_(True),
            )
        )
        if assignment is None:
            raise Forbidden("Only a contributor assigned on-chain can consent to cancellation.")
        if escrow.state != EscrowState.CANCEL_REQUESTED:
            raise InvalidStateTransition("The requester has not requested cancellation on-chain.")
        locked = await _assigned_address(session, assignment)
        if locked and locked != wallet:
            raise ValidationFailed("Sign with the wallet that was assigned on-chain.", code="wrong_wallet")
        return _Plan(
            soroban.consent_cancel(wallet, bid),
            TxType.CANCEL_CONSENT,
            "Consent to the cancellation and release your on-chain assignment.",
            assignment_id=assignment.id,
        )

    if action == ChainAction.REFUND:
        _require_owner(bounty, user)
        _require_requester_wallet(escrow, wallet)
        if bounty.status not in (BountyStatus.CANCEL_REQUESTED, BountyStatus.EXPIRED):
            raise InvalidStateTransition("Cancel the bounty before requesting a refund.")
        if escrow.state == EscrowState.FUNDED:
            raise InvalidStateTransition("Request cancellation on-chain first (action REQUEST_CANCEL).")
        if escrow.state not in (EscrowState.AWAITING_FUNDING, EscrowState.CANCEL_REQUESTED):
            raise InvalidStateTransition("The escrow cannot be refunded in its current state.")
        refundable = escrow.funded_amount - escrow.paid_out_amount - escrow.refunded_amount
        return _Plan(
            soroban.refund(wallet, bid),
            TxType.REFUND,
            f"Refund {_money(refundable, escrow)} to your wallet.",
            amount=refundable,
            destination=wallet,
        )

    if action == ChainAction.RAISE_DISPUTE:
        dispute = await session.get(Dispute, req.dispute_id) if req.dispute_id else None
        if (
            dispute is None
            or dispute.bounty_id != bounty.id
            or dispute.status not in (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW)
        ):
            raise NotFound("Open dispute not found.")
        if user.id not in (bounty.requester_id, dispute.contributor_id):
            raise Forbidden("Only the parties to the dispute can freeze the escrow.")
        if escrow.state not in (EscrowState.FUNDED, EscrowState.CANCEL_REQUESTED):
            raise InvalidStateTransition("The escrow cannot be frozen in its current state.")
        # The contract can only leave `Disputed` through resolve_dispute for a contributor who is *assigned*
        # on-chain. Freezing for anyone else would lock the escrow forever, so require that assignment.
        disputed = await session.scalar(
            select(BountyAssignment).where(
                BountyAssignment.bounty_id == bounty.id,
                BountyAssignment.contributor_id == dispute.contributor_id,
                BountyAssignment.status == AssignmentStatus.ACTIVE,
            )
        )
        onchain = (
            await _assigned_address(session, disputed) if disputed and disputed.onchain_assigned else None
        )
        if not onchain or await get_adapter().read_assignment(bid, onchain, escrow.contract_id) != "Assigned":
            raise InvalidStateTransition(
                "The disputed contributor is not assigned on-chain, so the arbiter could never release a frozen "
                "escrow. The dispute will be resolved off-chain by a moderator instead."
            )
        return _Plan(
            soroban.raise_dispute(wallet, bid),
            TxType.DISPUTE_RAISE,
            "Freeze the escrow on-chain while the dispute is reviewed.",
            dispute_id=dispute.id,
        )

    if action == ChainAction.RESOLVE_DISPUTE:
        dispute = await session.get(Dispute, req.dispute_id) if req.dispute_id else None
        if dispute is None or dispute.bounty_id != bounty.id:
            raise NotFound("Dispute not found.")
        if dispute.resolution not in (
            DisputeResolution.RELEASE_TO_CONTRIBUTOR,
            DisputeResolution.REFUND_TO_REQUESTER,
        ):
            raise InvalidStateTransition(
                "Record a release or refund resolution before executing it on-chain."
            )
        if escrow.state != EscrowState.DISPUTED:
            raise InvalidStateTransition(
                "The escrow is not frozen on-chain; no on-chain resolution is required."
            )
        escrow_chain.guard_resolve(escrow)
        if escrow.arbiter_address and wallet != escrow.arbiter_address:
            raise ValidationFailed("Sign with the escrow's arbiter wallet.", code="wrong_wallet")
        assignment = await session.scalar(
            select(BountyAssignment).where(
                BountyAssignment.bounty_id == bounty.id,
                BountyAssignment.contributor_id == dispute.contributor_id,
                BountyAssignment.status == AssignmentStatus.ACTIVE,
            )
        )
        if assignment is None or not assignment.onchain_assigned:
            raise InvalidStateTransition("The disputed contributor is not assigned on-chain.")
        contributor = await _contributor_address(session, assignment)
        pay = dispute.resolution == DisputeResolution.RELEASE_TO_CONTRIBUTOR
        call = soroban.resolve_dispute(wallet, bid, contributor, pay)
        desc = (
            "Release the reward to the contributor."
            if pay
            else "Release the contributor's claim (enables refund)."
        )
        return _Plan(
            call,
            TxType.DISPUTE_RESOLVE,
            desc,
            amount=bounty.reward_amount if pay else None,
            destination=contributor,
            assignment_id=assignment.id,
            dispute_id=dispute.id,
        )

    raise ValidationFailed(f"Unsupported action {action}.")


_TX_HASH_CONSTRAINT = "uq_bountyflow_blockchain_transactions_network_hash"


async def _reuse_identical_transaction(
    session: AsyncSession, user: User, bounty: Bounty, plan: _Plan, prepared: PreparedCall
) -> BlockchainTransaction:
    """Identical inputs (same wallet sequence number, contract arguments and one-second time bounds, e.g. a double
    click on "prepare") build a byte-identical transaction whose hash is already recorded, and ``(network, hash)`` is
    unique. The same transaction is handed out again as long as it is the caller's same action and never reached
    the network; anything else is refused (preparing again a moment later yields a new transaction)."""
    existing = await session.scalar(
        select(BlockchainTransaction)
        .where(
            BlockchainTransaction.network == get_network().network,
            BlockchainTransaction.transaction_hash == prepared.tx_hash,
        )
        .with_for_update(of=BlockchainTransaction)
        .execution_options(populate_existing=True)
    )
    reusable = (
        existing is not None
        and existing.user_id == user.id
        and existing.bounty_id == bounty.id
        and existing.transaction_type == plan.tx_type
        and existing.submission_id == plan.submission_id
        and existing.assignment_id == plan.assignment_id
        and existing.dispute_id == plan.dispute_id
        and existing.submitted_at is None
        and existing.status in (TxStatus.SIGNATURE_REQUIRED, TxStatus.EXPIRED)
    )
    if existing is None or not reusable:
        await session.rollback()
        raise Conflict(
            "An identical transaction was prepared moments ago. Please try again in a few seconds."
        )
    existing.status = TxStatus.SIGNATURE_REQUIRED
    existing.failure_reason = None
    existing.unsigned_xdr = prepared.unsigned_xdr
    existing.expires_at = prepared.expires_at
    return existing


async def prepare_action(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, req: PrepareRequest
) -> PreparedTransactionOut:
    network = get_network()
    if not network.is_configured:
        raise ServiceUnavailable(
            "On-chain escrow is not configured on this server (SOROBAN_CONTRACT_ID / "
            "STELLAR_NATIVE_ASSET_CONTRACT_ID)."
        )
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None:
        raise NotFound("Bounty not found.")
    try:
        plan = await _plan(session, user, bounty, req)
        # Sanctions screening of the signing wallet, of any account the action pays or binds, and of every
        # leg of a batch payout (it settles atomically, so one sanctioned payee blocks the whole batch).
        await screening.enforce(
            user_id=user.id,
            addresses=screening.chain_addresses(req.wallet_address, plan.destination, plan.metadata),
            context=screening.chain_context(req.action.value),
            bounty_id=bounty.id,
        )
        # Asset guards: a funding wallet without the asset, or a contributor wallet that cannot receive it
        # (no trustline), would fail on-chain; refuse it now with a specific message.
        escrow = await bounty_repo.get_escrow(session, bounty.id)
        # Every call goes to the contract this bounty's escrow lives on (v1 escrows stay on the v1 deployment).
        plan.call = soroban.on_contract(plan.call, escrow.contract_id if escrow else None)
        asset_identifier = escrow.asset_identifier if escrow else bounty.reward_asset_identifier
        await asset_checks.check_before_prepare(
            session,
            bounty,
            asset_identifier,
            plan.tx_type,
            source=req.wallet_address,
            amount=plan.amount,
            destination=plan.destination,
            assignment_id=plan.assignment_id,
            actor_id=user.id,
            legs=plan.metadata.get("legs"),  # a batch pays atomically: every leg is checked before signing
        )
        prepared = await get_adapter().prepare(plan.call, req.wallet_address)
    except ContractError as exc:
        await session.rollback()
        raise ValidationFailed(
            exc.message, code="contract_rejected", details={"contract_error": exc.name}
        ) from exc
    except AccountNotFound as exc:
        await session.rollback()
        raise ValidationFailed(str(exc), code="account_not_found") from exc
    except ChainUnavailable as exc:
        await session.rollback()
        raise BlockchainError(str(exc)) from exc

    # Supersede this user's earlier unsigned transactions for the same bounty/action.
    await session.execute(
        update(BlockchainTransaction)
        .where(
            BlockchainTransaction.bounty_id == bounty.id,
            BlockchainTransaction.user_id == user.id,
            BlockchainTransaction.transaction_type == plan.tx_type,
            BlockchainTransaction.status == TxStatus.SIGNATURE_REQUIRED,
        )
        .values(status=TxStatus.EXPIRED, failure_reason="Superseded by a newer prepared transaction.")
    )
    tx = BlockchainTransaction(
        id=uuid.uuid4(),
        bounty_id=bounty.id,
        user_id=user.id,
        transaction_hash=prepared.tx_hash,
        transaction_type=plan.tx_type,
        network=network.network,
        amount=plan.amount,
        asset_identifier=asset_identifier if plan.amount is not None else None,
        status=TxStatus.SIGNATURE_REQUIRED,
        source_address=req.wallet_address,
        destination_address=plan.destination,
        contract_id=plan.call.contract_id or network.contract_id,
        function_name=plan.call.function,
        unsigned_xdr=prepared.unsigned_xdr,
        expires_at=prepared.expires_at,
        fee_stroops=prepared.fee_stroops,
        submission_id=plan.submission_id,
        assignment_id=plan.assignment_id,
        dispute_id=plan.dispute_id,
        verification_metadata={"action": req.action.value, "args": plan.call.native, **plan.metadata},
    )
    try:
        async with session.begin_nested():  # the payment record below references this row
            session.add(tx)
            await session.flush()
    except IntegrityError as exc:
        if _TX_HASH_CONSTRAINT not in str(exc.orig):
            raise
        tx = await _reuse_identical_transaction(session, user, bounty, plan, prepared)
    if plan.tx_type == TxType.PAYOUT and plan.submission_id:
        await session.execute(
            update(PaymentRecord)
            .where(PaymentRecord.submission_id == plan.submission_id)
            .values(blockchain_transaction_id=tx.id)
        )
    await escrow_chain.after_prepare(session, tx)
    await session.commit()
    await session.refresh(tx)
    # A preview: the binding decision is taken again at submission (daily caps, sponsor balance).
    fee_sponsored = (await sponsorship.evaluate(session, tx)).sponsored
    return PreparedTransactionOut(
        transaction=serialize_tx(tx),
        unsigned_xdr=prepared.unsigned_xdr,
        network_passphrase=network.passphrase,
        network=network.network,
        summary=TxSummary(
            action=req.action,
            description=plan.description,
            amount=plan.amount,
            asset=asset_from_identifier(asset_identifier) if plan.amount is not None else None,
            fee_estimate_stroops=str(prepared.fee_stroops) if prepared.fee_stroops is not None else None,
            contract_id=plan.call.contract_id or network.contract_id,
            function_name=plan.call.function,
            fee_sponsored=fee_sponsored,
        ),
        expires_at=prepared.expires_at,
    )


# --- Submission ----------------------------------------------------------------------------


async def _acquire(lock_key: str, ttl: int = 30) -> bool:
    try:
        return bool(await get_redis().set(lock_key, "1", nx=True, ex=ttl))
    except Exception:
        return True  # Redis down: the DB row lock + unique constraints still prevent double effects


async def _release(lock_key: str) -> None:
    try:
        await get_redis().delete(lock_key)
    except Exception:  # noqa: S110
        pass


async def _load_tx(
    session: AsyncSession, tx_id: uuid.UUID, *, for_update: bool = False
) -> BlockchainTransaction:
    stmt = select(BlockchainTransaction).where(BlockchainTransaction.id == tx_id)
    if for_update:
        # populate_existing: decisions (e.g. "still SUBMITTED?") must use the locked, current row, never a stale
        # identity-map copy — otherwise an already-verified transaction could be re-applied (duplicate events).
        stmt = stmt.with_for_update(of=BlockchainTransaction).execution_options(populate_existing=True)
    tx = await session.scalar(stmt)
    if tx is None:
        raise NotFound("Transaction not found.")
    return tx


async def submit_transaction(
    session: AsyncSession, user: User, tx_id: uuid.UUID, signed_xdr: str
) -> BlockchainTransactionOut:
    lock = keys.tx_lock(f"submit:{tx_id}")
    if not await _acquire(lock):
        raise Conflict("This transaction is already being submitted.")
    try:
        tx = await _load_tx(session, tx_id, for_update=True)
        if tx.user_id != user.id:
            raise NotFound("Transaction not found.")
        if tx.status in (TxStatus.SUBMITTED, TxStatus.CONFIRMED):
            return serialize_tx(tx)  # idempotent re-submit
        if tx.status != TxStatus.SIGNATURE_REQUIRED:
            raise InvalidStateTransition(f"This transaction is {tx.status.value.lower()}; prepare a new one.")
        landed_earlier = False
        if tx.expires_at and tx.expires_at <= utcnow():
            # An earlier submit may have reached the network even though its response was lost (timeout).
            landed = await _network_has(tx)
            if landed is None:
                raise BlockchainError(
                    "The network could not be reached to check this transaction. Retry shortly."
                )
            if not landed:
                tx.status = TxStatus.EXPIRED
                tx.failure_reason = "The transaction expired before it was signed."
                await _on_failure(session, tx)
                await session.commit()
                raise InvalidStateTransition(
                    "The transaction expired before it was signed. Please prepare it again."
                )
            landed_earlier = True
        network = get_network()
        assert tx.transaction_hash is not None
        if tx.network != network.network:
            # A row prepared for another network (e.g. before a testnet -> mainnet switch) can never be submitted here.
            raise InvalidStateTransition(
                "This transaction was prepared for a different network. Please prepare it again."
            )
        try:
            # Checks the signed envelope against what was prepared; an eligible one is fee-bumped by the platform
            # sponsor, and a smart wallet's signed authorization is relayed (app/blockchain/sponsorship.py).
            submission = await sponsorship.prepare_submission(session, tx, signed_xdr)
        except EnvelopeMismatch as exc:
            raise ValidationFailed(str(exc), code="signature_invalid") from exc
        if not landed_earlier and tx.transaction_type == TxType.DISPUTE_RAISE and tx.dispute_id:
            # Freezing the escrow only makes sense while the dispute is open: once a moderator closed it
            # off-chain (e.g. DISMISSED), a frozen escrow could never be routed on-chain again.
            dispute_status = await session.scalar(select(Dispute.status).where(Dispute.id == tx.dispute_id))
            if dispute_status not in (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW):
                tx.status = TxStatus.EXPIRED
                tx.failure_reason = "The dispute was closed before the escrow was frozen."
                await session.commit()
                raise InvalidStateTransition(
                    "This dispute is already closed, so the escrow will not be frozen."
                )
        if not landed_earlier:
            try:
                submitted_hash = await get_adapter().submit(submission.xdr, tx.transaction_hash)
            except ChainRejected as exc:
                # A re-send of a transaction that already reached the network is rejected (e.g. txBAD_SEQ) —
                # that is not a failure of the transaction itself. Ask the network before recording FAILED.
                landed = await _network_has(tx)
                if landed is None:
                    raise BlockchainError(
                        "The network could not be reached to check this transaction. Retry shortly."
                    ) from exc
                if not landed:
                    tx.status = TxStatus.FAILED
                    tx.failure_reason = str(exc)
                    tx.verification_metadata = {**tx.verification_metadata, "result_code": exc.code}
                    await _on_failure(session, tx)
                    await sponsorship.settle(session, tx)
                    await session.commit()
                    await _emit_after(session, tx)
                    return serialize_tx(tx)
                submitted_hash = tx.transaction_hash
            except ChainUnavailable as exc:
                raise BlockchainError(str(exc)) from exc
            if submitted_hash != tx.transaction_hash:
                logger.error("submitted_hash_mismatch", tx_id=str(tx.id))
                raise BlockchainError("The network returned an unexpected transaction hash.")
        bounty = await _record_submitted(session, tx, user.id)
        await session.commit()
        if bounty is not None:
            await invalidate_bounty(str(bounty.id), bounty.slug)
    finally:
        await _release(lock)
    # Best-effort immediate verification (the worker and sweep job guarantee eventual verification). The
    # submission is already committed, so no verification problem may turn this response into an error.
    try:
        await verify_transaction(session, tx_id)
    except ChainUnavailable:
        await session.rollback()
    except Exception:
        logger.exception("post_submit_verification_failed", tx_id=str(tx_id))
        await session.rollback()
    await session.refresh(tx)
    return serialize_tx(tx)


async def _network_has(tx: BlockchainTransaction) -> bool | None:
    """Whether the network already has a result for this transaction's hash (it was submitted after all, e.g.
    by an attempt whose response was lost). None when the network cannot be asked right now."""
    if not tx.transaction_hash or tx.network != get_network().network:
        return False  # rows prepared for another network can never be on this one
    try:
        outcome = await get_adapter().get_outcome(tx.transaction_hash)
    except ChainUnavailable:
        return None
    return outcome.status in ("SUCCESS", "FAILED")


async def _record_submitted(
    session: AsyncSession, tx: BlockchainTransaction, actor_id: uuid.UUID | None
) -> Bounty | None:
    """Marks a transaction SUBMITTED (it reached the network) with its domain side effects. Lock order: the
    transaction row is already locked by the caller; the bounty row is locked here."""
    tx.status = TxStatus.SUBMITTED
    tx.submitted_at = utcnow()
    bounty = await bounty_repo.get(session, tx.bounty_id, for_update=True) if tx.bounty_id else None
    if (
        bounty is not None
        and tx.transaction_type in (TxType.ESCROW_CREATE, TxType.ESCROW_FUND)
        and bounty.status == BountyStatus.OPEN
    ):
        bounty_service.change_status(
            session,
            bounty,
            BountyStatus.FUNDING_PENDING,
            actor_id=actor_id,
            event_type=EventType.BOUNTY_FUNDING_SUBMITTED,
        )
    if tx.transaction_type == TxType.PAYOUT and tx.submission_id:
        await session.execute(
            update(PaymentRecord)
            .where(PaymentRecord.submission_id == tx.submission_id)
            .values(payment_status=PaymentStatus.SUBMITTED, blockchain_transaction_id=tx.id)
        )
    await escrow_chain.on_submitted(session, tx)
    audit.record(
        session,
        actor_id=actor_id,
        action="transaction.submitted",
        entity_type="transaction",
        entity_id=tx.id,
        bounty_id=tx.bounty_id,
        metadata={
            "type": tx.transaction_type.value,
            "hash": tx.transaction_hash,
        },
    )
    add_event(
        session,
        event_type=EventType.TX_SUBMITTED,
        aggregate_type="transaction",
        aggregate_id=tx.id,
        actor_id=actor_id,
        payload=_tx_payload(tx),
    )
    return bounty


def _tx_payload(tx: BlockchainTransaction) -> dict[str, Any]:
    return {
        "transaction_id": tx.id,
        "bounty_id": tx.bounty_id,
        "transaction_type": tx.transaction_type.value,
        "status": tx.status.value,
    }


async def _invalidate_party_profiles(session: AsyncSession, tx: BlockchainTransaction) -> None:
    """A verified settlement changes both parties' profile stats (completed bounties, rewards received/paid);
    invalidate after the commit so no reader can re-cache the pre-commit values."""
    user_ids: set[uuid.UUID] = set()
    if tx.bounty_id is not None:
        requester_id = await session.scalar(select(Bounty.requester_id).where(Bounty.id == tx.bounty_id))
        if requester_id is not None:
            user_ids.add(requester_id)
    if tx.assignment_id is not None:
        contributor_id = await session.scalar(
            select(BountyAssignment.contributor_id).where(BountyAssignment.id == tx.assignment_id)
        )
        if contributor_id is not None:
            user_ids.add(contributor_id)
    if user_ids:
        usernames = (await session.scalars(select(User.username).where(User.id.in_(user_ids)))).all()
        await invalidate_profile(*usernames)


async def _emit_after(session: AsyncSession, tx: BlockchainTransaction) -> None:
    if tx.bounty_id:
        bounty = await bounty_repo.get(session, tx.bounty_id)
        if bounty:
            await invalidate_bounty(str(bounty.id), bounty.slug)


# --- Verification & settlement --------------------------------------------------------------


async def verify_transaction(session: AsyncSession, tx_id: uuid.UUID) -> TxStatus | None:
    """Idempotently checks a SUBMITTED transaction's outcome and applies verified effects."""
    lock = keys.tx_lock(f"verify:{tx_id}")
    if not await _acquire(lock, ttl=60):
        return None
    try:
        # Network I/O first, with no row lock held (the Redis lock serialises verifications of one transaction):
        # the outcome and, for a success, the contract state it is settled from. The row is locked afterwards and
        # its status checked again, and everything verified is written in this one transaction.
        peek = await _load_tx(session, tx_id)
        if peek.status != TxStatus.SUBMITTED or not peek.transaction_hash:
            current = peek.status
            await session.rollback()
            return current
        adapter = get_adapter()
        outcome = await adapter.get_outcome(peek.transaction_hash)
        settlement = await _read_settlement_state(session, peek) if outcome.status == "SUCCESS" else None
        tx = await _load_tx(session, tx_id, for_update=True)
        current = tx.status
        if current != TxStatus.SUBMITTED or not tx.transaction_hash:
            await session.rollback()  # expires `tx`; use the captured status
            return current
        tx.verification_attempts += 1
        if outcome.status == "PENDING":
            # Known to the network but not settled yet: only SUCCESS may ever be recorded as CONFIRMED.
            await session.commit()
            return TxStatus.SUBMITTED
        if outcome.status == "NOT_FOUND":
            deadline = (tx.expires_at or utcnow()) + EXPIRY_GRACE
            if utcnow() > deadline:
                tx.status = TxStatus.EXPIRED
                tx.failure_reason = "The network never included this transaction before it expired."
                await _on_failure(session, tx)
                await sponsorship.settle(session, tx, outcome)
                add_event(
                    session,
                    event_type=EventType.TX_FAILED,
                    aggregate_type="transaction",
                    aggregate_id=tx.id,
                    payload=_tx_payload(tx),
                )
            await session.commit()
            await _emit_after(session, tx)
            return tx.status
        if outcome.status == "FAILED":
            tx.status = TxStatus.FAILED
            tx.failure_reason = outcome.failure_reason or "The transaction failed."
            tx.ledger_sequence = outcome.ledger
            tx.verification_metadata = {**tx.verification_metadata, "result_code": outcome.result_code}
            await _on_failure(session, tx)
            await sponsorship.settle(session, tx, outcome)
            audit.record(
                session,
                actor_id=tx.user_id,
                action="transaction.failed",
                entity_type="transaction",
                entity_id=tx.id,
                bounty_id=tx.bounty_id,
                metadata={"type": tx.transaction_type.value, "reason": tx.failure_reason},
            )
            add_event(
                session,
                event_type=EventType.TX_FAILED,
                aggregate_type="transaction",
                aggregate_id=tx.id,
                payload=_tx_payload(tx),
            )
            await session.commit()
            await _emit_after(session, tx)
            return tx.status
        # SUCCESS — confirmed on the network. Now reconcile from contract state.
        tx.status = TxStatus.CONFIRMED
        tx.ledger_sequence = outcome.ledger
        tx.confirmed_at = outcome.ledger_close_time or utcnow()
        tx.verification_metadata = {
            **tx.verification_metadata,
            "verified_at": utcnow().isoformat(),
        }
        await _on_success(session, tx, settlement)
        await sponsorship.settle(session, tx, outcome)
        audit.record(
            session,
            actor_id=tx.user_id,
            action="transaction.confirmed",
            entity_type="transaction",
            entity_id=tx.id,
            bounty_id=tx.bounty_id,
            metadata={
                "type": tx.transaction_type.value,
                "hash": tx.transaction_hash,
                "ledger": tx.ledger_sequence,
            },
        )
        add_event(
            session,
            event_type=EventType.TX_CONFIRMED,
            aggregate_type="transaction",
            aggregate_id=tx.id,
            payload=_tx_payload(tx),
        )
        await session.commit()
        await _emit_after(session, tx)
        await _invalidate_party_profiles(session, tx)
        await invalidate_public_stats()
        return tx.status
    finally:
        await _release(lock)


async def _on_failure(session: AsyncSession, tx: BlockchainTransaction) -> None:
    await escrow_chain.on_failure(session, tx)
    if tx.transaction_type in (TxType.ESCROW_CREATE, TxType.ESCROW_FUND) and tx.bounty_id:
        bounty = await bounty_repo.get(session, tx.bounty_id, for_update=True)
        if bounty is not None and bounty.status == BountyStatus.FUNDING_PENDING:
            bounty_service.change_status(
                session, bounty, BountyStatus.OPEN, actor_id=None, reason="funding transaction failed"
            )
    if tx.transaction_type == TxType.PAYOUT and tx.submission_id:
        await session.execute(
            update(PaymentRecord)
            .where(
                PaymentRecord.submission_id == tx.submission_id,
                PaymentRecord.payment_status.in_([PaymentStatus.SIGNATURE_REQUIRED, PaymentStatus.SUBMITTED]),
            )
            .values(payment_status=PaymentStatus.FAILED)
        )
        payment = await session.scalar(
            select(PaymentRecord).where(PaymentRecord.submission_id == tx.submission_id)
        )
        bounty = await bounty_repo.get(session, tx.bounty_id) if tx.bounty_id else None
        if payment is not None and bounty is not None:
            add_event(
                session,
                event_type=EventType.PAYMENT_FAILED,
                aggregate_type="payment",
                aggregate_id=payment.id,
                payload={
                    "bounty_id": bounty.id,
                    "requester_id": bounty.requester_id,
                    "contributor_id": payment.contributor_id,
                    "title": bounty.title,
                    "amount": fmt(payment.amount),
                    "asset": payment.asset_identifier,
                    "asset_code": asset_from_identifier(payment.asset_identifier).code,
                    "transaction_id": tx.id,
                },
            )


class _SettlementState:
    """Contract state a confirmed transaction is settled from, read before any row lock is taken."""

    def __init__(
        self,
        snapshot: EscrowSnapshot | None,
        trusted: bool,
        destination_state: str | None,
        v2: escrow_chain.SettlementReads | None,
    ) -> None:
        self.snapshot = snapshot
        self.trusted = trusted
        self.destination_state = destination_state
        self.v2 = v2


async def _read_settlement_state(session: AsyncSession, tx: BlockchainTransaction) -> _SettlementState | None:
    if tx.bounty_id is None:
        return None
    escrow = await bounty_repo.get_escrow(session, tx.bounty_id)
    if escrow is None:
        return None
    snapshot, trusted = await _read_trusted_snapshot(session, escrow)
    destination_state = None
    if tx.destination_address and tx.transaction_type in (
        TxType.ASSIGN,
        TxType.PAYOUT,
        TxType.DISPUTE_RESOLVE,
    ):
        destination_state = await get_adapter().read_assignment(
            _bid(escrow), tx.destination_address, escrow.contract_id
        )
    v2 = await escrow_chain.read_for_settlement(escrow, tx) if trusted else None
    return _SettlementState(snapshot, trusted, destination_state, v2)


async def _on_success(
    session: AsyncSession, tx: BlockchainTransaction, settlement: _SettlementState | None
) -> None:
    if tx.bounty_id is None or settlement is None:
        return
    # Lock order: bounty, then escrow, then dependents. The chain was read before (no lock across network I/O).
    bounty = await bounty_repo.get(session, tx.bounty_id, for_update=True)
    escrow = await bounty_repo.get_escrow(session, tx.bounty_id, for_update=True)
    if bounty is None or escrow is None:
        return
    snapshot = settlement.snapshot
    if not settlement.trusted:
        # SEC-01: nothing is ever settled from a foreign escrow (payouts, funding and refunds stay untouched).
        logger.error("confirmed_transaction_on_foreign_escrow", tx_id=str(tx.id), bounty_id=str(bounty.id))
        return
    changed = apply_snapshot(escrow, snapshot)
    if changed:
        logger.info("escrow_reconciled", bounty_id=str(bounty.id), fields=changed, state=escrow.state.value)
    await escrow_chain.after_snapshot(session, bounty, snapshot, tx)

    state = settlement.destination_state
    if tx.transaction_type == TxType.ASSIGN and tx.assignment_id and tx.destination_address:
        assignment = await session.get(BountyAssignment, tx.assignment_id, with_for_update=True)
        if assignment is not None and state in ("Assigned", "Paid"):
            assignment.onchain_assigned = True

    elif tx.transaction_type == TxType.PAYOUT and tx.submission_id and tx.destination_address:
        if state == "Paid":
            await _settle_payout(session, bounty, tx)
        else:
            logger.error("payout_not_reflected_on_chain", tx_id=str(tx.id), state=state)

    elif tx.transaction_type == TxType.CANCEL_CONSENT and tx.assignment_id:
        assignment = await session.get(BountyAssignment, tx.assignment_id, with_for_update=True)
        if assignment is not None and assignment.status == AssignmentStatus.ACTIVE:
            assignment.status = AssignmentStatus.RELEASED
            assignment.released_at = utcnow()
            assignment.onchain_assigned = False

    elif tx.transaction_type == TxType.DISPUTE_RESOLVE and tx.assignment_id and tx.destination_address:
        assignment = await session.get(BountyAssignment, tx.assignment_id, with_for_update=True)
        if state == "Paid":
            await _settle_payout(session, bounty, tx)
            await _review_disputed_submission(session, tx, approved=True)
        elif assignment is not None and state is None:
            assignment.status = AssignmentStatus.RELEASED
            assignment.released_at = utcnow()
            assignment.onchain_assigned = False
            await _review_disputed_submission(session, tx, approved=False)
        # A multi-arbiter escrow stays Disputed until enough arbiters approved; only then does work resume.
        if bounty.status == BountyStatus.DISPUTED and escrow.state != EscrowState.DISPUTED:
            await _restore_after_dispute(session, bounty, escrow)

    elif tx.transaction_type in escrow_chain.V2_TX_TYPES:
        await escrow_chain.on_success(session, bounty, escrow, snapshot, tx, settlement.v2)

    await _apply_escrow_to_bounty(session, bounty, escrow, tx)


async def _settle_payout(session: AsyncSession, bounty: Bounty, tx: BlockchainTransaction) -> None:
    assignment = (
        await session.get(BountyAssignment, tx.assignment_id, with_for_update=True)
        if tx.assignment_id
        else None
    )
    if assignment is None:
        return
    submission = await session.scalar(
        select(BountySubmission).where(BountySubmission.assignment_id == assignment.id)
    )
    payment = None
    if submission is not None:
        payment = await session.scalar(
            select(PaymentRecord)
            .where(PaymentRecord.submission_id == submission.id)
            .with_for_update(of=PaymentRecord)
        )
        if payment is None:
            payment = PaymentRecord(
                id=uuid.uuid4(),
                bounty_id=bounty.id,
                contributor_id=assignment.contributor_id,
                submission_id=submission.id,
                amount=bounty.reward_amount,
                asset_identifier=tx.asset_identifier or bounty.reward_asset_identifier,
                payment_status=PaymentStatus.CREATED,
            )
            session.add(payment)
    now = utcnow()
    if payment is not None and payment.payment_status != PaymentStatus.CONFIRMED:
        payment.payment_status = PaymentStatus.CONFIRMED
        payment.settled_at = now
        payment.blockchain_transaction_id = tx.id
    assignment.status = AssignmentStatus.COMPLETED
    assignment.completed_at = now
    contributor = await session.get(User, assignment.contributor_id)
    audit.record(
        session,
        actor_id=tx.user_id,
        action="payment.confirmed",
        entity_type="payment",
        entity_id=payment.id if payment else tx.id,
        bounty_id=bounty.id,
        metadata={
            "amount": fmt(bounty.reward_amount),
            "asset_code": asset_from_identifier(tx.asset_identifier or bounty.reward_asset_identifier).code,
            "hash": tx.transaction_hash,
            "contributor": contributor.username if contributor else None,
        },
    )
    add_event(
        session,
        event_type=EventType.PAYMENT_CONFIRMED,
        aggregate_type="payment",
        aggregate_id=payment.id if payment else tx.id,
        payload={
            "bounty_id": bounty.id,
            "requester_id": bounty.requester_id,
            "contributor_id": assignment.contributor_id,
            "title": bounty.title,
            "amount": fmt(bounty.reward_amount),
            "asset": tx.asset_identifier or bounty.reward_asset_identifier,
            "asset_code": asset_from_identifier(tx.asset_identifier or bounty.reward_asset_identifier).code,
            "transaction_id": tx.id,
        },
    )
    if contributor is not None:
        await invalidate_profile(contributor.username)


async def _review_disputed_submission(
    session: AsyncSession, tx: BlockchainTransaction, *, approved: bool
) -> None:
    """Mirror the arbiter's verified on-chain decision on the contributor's submission (as the off-chain
    resolution does), so a paid submission is APPROVED and a released one is not left awaiting review."""
    if tx.assignment_id is None:
        return
    submission = await session.scalar(
        select(BountySubmission)
        .where(BountySubmission.assignment_id == tx.assignment_id)
        .with_for_update(of=BountySubmission)
    )
    if submission is None or submission.status == SubmissionStatus.APPROVED:
        return
    submission.status = SubmissionStatus.APPROVED if approved else SubmissionStatus.REJECTED
    submission.review_feedback = (
        "Approved through dispute resolution." if approved else "Rejected through dispute resolution."
    )
    submission.reviewer_id = tx.user_id
    submission.reviewed_at = utcnow()


async def _restore_after_dispute(session: AsyncSession, bounty: Bounty, escrow: BountyEscrow) -> None:
    if escrow.state == EscrowState.COMPLETED:
        return  # handled by _apply_escrow_to_bounty
    before = (bounty.metadata_ or {}).get("status_before_dispute")
    # Also honour an off-chain cancellation request that predates the dispute (the escrow may still be FUNDED
    # on-chain if the requester had not yet signed REQUEST_CANCEL).
    if escrow.state == EscrowState.CANCEL_REQUESTED or before == BountyStatus.CANCEL_REQUESTED.value:
        bounty_service.change_status(
            session, bounty, BountyStatus.CANCEL_REQUESTED, actor_id=None, reason="dispute resolved"
        )
        return
    bounty_service.change_status(
        session, bounty, BountyStatus.FUNDED, actor_id=None, reason="dispute resolved"
    )
    await session.flush()
    await bounty_service.recompute_operational_status(session, bounty, None)


async def _apply_escrow_to_bounty(
    session: AsyncSession, bounty: Bounty, escrow: BountyEscrow, tx: BlockchainTransaction
) -> None:
    """Moves the bounty lifecycle forward based on verified escrow state."""
    status = bounty.status
    if escrow.state == EscrowState.FUNDED and status in (BountyStatus.OPEN, BountyStatus.FUNDING_PENDING):
        bounty_service.change_status(
            session, bounty, BountyStatus.FUNDED, actor_id=tx.user_id, event_type=EventType.BOUNTY_FUNDED
        )
    elif escrow.state == EscrowState.AWAITING_FUNDING and status == BountyStatus.FUNDING_PENDING:
        bounty_service.change_status(
            session, bounty, BountyStatus.OPEN, actor_id=tx.user_id, reason="partially funded"
        )
    elif escrow.state == EscrowState.CANCELLED:
        await bounty_service.finalize_cancellation(session, bounty, tx.user_id)
        refund = escrow.refunded_amount
        add_event(
            session,
            event_type=EventType.REFUND_CONFIRMED,
            aggregate_type="payment",
            aggregate_id=tx.id,
            payload={
                "bounty_id": bounty.id,
                "requester_id": bounty.requester_id,
                "title": bounty.title,
                "amount": fmt(refund),
                "asset": escrow.asset_identifier,
                "asset_code": _asset_code(escrow),
                "transaction_id": tx.id,
            },
        )
    elif escrow.state == EscrowState.COMPLETED and status not in sm.TERMINAL:
        if sm.can_transition(status, BountyStatus.COMPLETED):
            bounty_service.change_status(
                session,
                bounty,
                BountyStatus.COMPLETED,
                actor_id=tx.user_id,
                event_type=EventType.BOUNTY_COMPLETED,
            )
    elif tx.transaction_type in (TxType.PAYOUT, TxType.DISPUTE_RESOLVE, *escrow_chain.RECOMPUTE_TX_TYPES):
        await session.flush()
        await bounty_service.recompute_operational_status(session, bounty, tx.user_id)


async def sweep_pending_transactions(session: AsyncSession, limit: int = 50) -> int:
    """Worker job: verifies SUBMITTED transactions and expires stale unsigned ones."""
    now = utcnow()
    stale = (
        (
            await session.scalars(
                select(BlockchainTransaction)
                .where(
                    BlockchainTransaction.status == TxStatus.SIGNATURE_REQUIRED,
                    BlockchainTransaction.expires_at < now,
                )
                .with_for_update(skip_locked=True, of=BlockchainTransaction)
                .limit(limit)
            )
        )
        .unique()
        .all()
    )
    touched: list[Bounty] = []
    for tx in stale:
        # A submit whose response was lost leaves the row SIGNATURE_REQUIRED although the network has it.
        # Expiring it would drop a real payout/funding, so ask the network first.
        landed = await _network_has(tx)
        if landed is None:
            continue  # the network is unreachable: decide on a later run
        if landed:
            bounty = await _record_submitted(session, tx, tx.user_id)  # verified by the pending pass below
            if bounty is not None:
                touched.append(bounty)
            continue
        tx.status = TxStatus.EXPIRED
        tx.failure_reason = "Expired before it was signed."
        await sponsorship.settle(session, tx)
        await escrow_chain.on_expired(session, tx)
        if tx.transaction_type == TxType.PAYOUT and tx.submission_id:
            await session.execute(
                update(PaymentRecord)
                .where(
                    PaymentRecord.submission_id == tx.submission_id,
                    PaymentRecord.payment_status == PaymentStatus.SIGNATURE_REQUIRED,
                )
                .values(payment_status=PaymentStatus.CREATED)
            )
    await session.commit()
    for bounty in touched:  # e.g. OPEN -> FUNDING_PENDING
        await invalidate_bounty(str(bounty.id), bounty.slug)
    pending_ids = (
        await session.scalars(
            select(BlockchainTransaction.id)
            .where(BlockchainTransaction.status == TxStatus.SUBMITTED)
            .order_by(BlockchainTransaction.submitted_at)
            .limit(limit)
        )
    ).all()
    processed = 0
    for tx_id in pending_ids:
        try:
            await verify_transaction(session, tx_id)
            processed += 1
        except ChainUnavailable as exc:
            logger.warning("verification_deferred", tx_id=str(tx_id), error=str(exc))
            await session.rollback()
            break
        except Exception:
            logger.exception("verification_failed", tx_id=str(tx_id))
            await session.rollback()
    return processed + len(stale)


async def reconcile_bounty(session: AsyncSession, bounty_id: uuid.UUID) -> None:
    """Re-reads escrow state from chain and applies it (admin/debug and post-dispute checks)."""
    escrow = await bounty_repo.get_escrow(session, bounty_id, for_update=True)
    if escrow is None:
        return
    snapshot, trusted = await _read_trusted_snapshot(session, escrow)
    if not trusted:  # SEC-01: chain state is authoritative only for the escrow BountyFlow prepared
        await session.rollback()
        raise Conflict(_UNVERIFIED_ESCROW, code="escrow_unverified")
    apply_snapshot(escrow, snapshot)
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is not None:
        await escrow_chain.after_snapshot(session, bounty, snapshot, None)
    await session.commit()


# --- Queries --------------------------------------------------------------------------------


async def funding(session: AsyncSession, bounty_id: uuid.UUID, viewer: User | None) -> FundingOut:
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None or not bounty_service.can_view(bounty, viewer):
        raise NotFound("Bounty not found.")
    escrow = await bounty_repo.get_escrow(session, bounty_id)
    txs = await _bounty_txs(
        session, bounty, viewer, types=(TxType.ESCROW_CREATE, TxType.ESCROW_FUND, TxType.REFUND)
    )
    view = bounty_service.escrow_view(escrow)
    return FundingOut(
        funding_status=bounty_service.funding_status(bounty, escrow).value,
        escrow=view.model_dump(mode="json") if view else None,
        transactions=txs,
    )


async def _bounty_txs(
    session: AsyncSession, bounty: Bounty, viewer: User | None, types: tuple[TxType, ...] | None = None
) -> list[BlockchainTransactionOut]:
    stmt = select(BlockchainTransaction).where(BlockchainTransaction.bounty_id == bounty.id)
    privileged = viewer is not None and (
        viewer.id == bounty.requester_id or has_permission(viewer, Permission.TRANSACTION_VIEW_ALL)
    )
    if not privileged:
        stmt = stmt.where(
            BlockchainTransaction.status.in_([TxStatus.SUBMITTED, TxStatus.CONFIRMED, TxStatus.FAILED])
        )
    if types:
        stmt = stmt.where(BlockchainTransaction.transaction_type.in_(types))
    rows = (
        (await session.scalars(stmt.order_by(BlockchainTransaction.created_at.desc()).limit(100)))
        .unique()
        .all()
    )
    return [serialize_tx(t) for t in rows]


async def bounty_transactions(
    session: AsyncSession, bounty_id: uuid.UUID, viewer: User | None
) -> list[BlockchainTransactionOut]:
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None or not bounty_service.can_view(bounty, viewer):
        raise NotFound("Bounty not found.")
    return await _bounty_txs(session, bounty, viewer)


async def get_transaction(session: AsyncSession, ref: str, viewer: User | None) -> BlockchainTransactionOut:
    network = get_network()
    try:
        stmt = select(BlockchainTransaction).where(BlockchainTransaction.id == uuid.UUID(ref))
    except ValueError:
        stmt = select(BlockchainTransaction).where(
            BlockchainTransaction.transaction_hash == ref, BlockchainTransaction.network == network.network
        )
    tx = await session.scalar(stmt)
    if tx is None:
        raise NotFound("Transaction not found.")
    is_party = viewer is not None and (
        tx.user_id == viewer.id or has_permission(viewer, Permission.TRANSACTION_VIEW_ALL)
    )
    if tx.status in (TxStatus.SIGNATURE_REQUIRED, TxStatus.EXPIRED, TxStatus.CREATED) and not is_party:
        raise NotFound("Transaction not found.")
    if tx.status == TxStatus.SUBMITTED:
        tx_id = tx.id  # captured: a rollback below expires `tx`, and touching it then would lazy-load (500)
        try:
            await verify_transaction(session, tx_id)
        except ChainUnavailable:
            await session.rollback()
        tx = await session.scalar(
            select(BlockchainTransaction)
            .where(BlockchainTransaction.id == tx_id)
            .execution_options(populate_existing=True)
        )
        assert tx is not None
    return serialize_tx(tx)


async def my_transactions(
    session: AsyncSession, user: User, params: PageParams
) -> Page[BlockchainTransactionOut]:
    base = select(BlockchainTransaction).where(
        BlockchainTransaction.user_id == user.id, BlockchainTransaction.status != TxStatus.EXPIRED
    )
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(BlockchainTransaction.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[BlockchainTransactionOut].build([serialize_tx(t) for t in rows], total, params)


async def all_transactions(
    session: AsyncSession, status: TxStatus | None, tx_type: TxType | None, params: PageParams
) -> Page[BlockchainTransactionOut]:
    base = select(BlockchainTransaction)
    if status:
        base = base.where(BlockchainTransaction.status == status)
    if tx_type:
        base = base.where(BlockchainTransaction.transaction_type == tx_type)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(BlockchainTransaction.created_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[BlockchainTransactionOut].build([serialize_tx(t) for t in rows], total, params)


async def my_payments(
    session: AsyncSession, user: User, direction: str, params: PageParams
) -> Page[PaymentRecordOut]:
    base = select(PaymentRecord, Bounty.title, Bounty.slug).join(Bounty, Bounty.id == PaymentRecord.bounty_id)
    if direction == "sent":
        base = base.where(Bounty.requester_id == user.id)
    else:
        base = base.where(PaymentRecord.contributor_id == user.id)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.execute(
                base.order_by(PaymentRecord.created_at.desc()).offset(params.offset).limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[PaymentRecordOut].build(
        [serialize_payment(p, title, slug) for p, title, slug in rows], total, params
    )
