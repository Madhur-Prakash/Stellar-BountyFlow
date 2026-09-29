"""Wallet-signed asset operations: adding a trustline, and deploying a missing Stellar Asset Contract.

They follow the same lifecycle as escrow actions (see ``payments.service``): the backend builds the transaction
with the user's *verified* wallet as the source account, the wallet signs the exact XDR, the backend checks the
signed envelope (hash, source, signature) before submitting it, and an operation is CONFIRMED only once its effect
is read back from the network: the trustline appears on the account (Horizon), or the contract instance exists
(Soroban RPC).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import Account, TransactionBuilder

from app.blockchain import sponsorship
from app.blockchain.assets import SAC_DECIMALS, is_contract_address, parse_identifier
from app.blockchain.config import get_network
from app.blockchain.horizon import ClassicResult, HorizonUnavailable, get_horizon
from app.blockchain.soroban import ContractError
from app.blockchain.tokens import TokenMetadata, get_tokens
from app.blockchain.transactions import AccountNotFound, ChainRejected, ChainUnavailable, TxOutcome
from app.blockchain.verification import EnvelopeMismatch, verify_signed_envelope
from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.exceptions import (
    BlockchainError,
    Conflict,
    Forbidden,
    InvalidStateTransition,
    NotFound,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.money import display_amount
from app.core.rbac import Permission, has_permission
from app.core.schemas import asset_from_identifier
from app.core.security import utcnow
from app.modules.admin import audit
from app.modules.assets import service as registry
from app.modules.assets.checks import FRIENDBOT_HINT, invalidate_trustline
from app.modules.assets.models import (
    AssetKind,
    AssetOperation,
    AssetOperationKind,
    AssetOperationStatus,
    ContractStatus,
    RewardAsset,
)
from app.modules.assets.schemas import AssetOperationOut, PreparedAssetOperation
from app.modules.users import repository as users_repo
from app.modules.users.models import User
from app.modules.wallets.models import SponsoredTransaction, SponsorshipStatus

logger = get_logger(__name__)

TRUSTLINE_RESERVE = Decimal("0.5")  # a trustline is a subentry: it locks one base reserve
CLASSIC_MAX_FEE = 10_000  # stroops (0.001 XLM): ample for a single changeTrust on Testnet
EXPIRY_GRACE = timedelta(seconds=90)


def serialize(op: AssetOperation, asset: RewardAsset) -> AssetOperationOut:
    network = get_network()
    unsent = op.status in (AssetOperationStatus.SIGNATURE_REQUIRED, AssetOperationStatus.EXPIRED)
    return AssetOperationOut(
        id=op.id,
        kind=op.kind,
        status=op.status,
        asset=asset_from_identifier(asset.identifier),
        network=op.network,
        source_address=op.source_address,
        transaction_hash=op.transaction_hash,
        ledger_sequence=op.ledger_sequence,
        submitted_at=op.submitted_at,
        confirmed_at=op.confirmed_at,
        failure_reason=op.failure_reason,
        explorer_url=None if unsent else network.tx_url(op.transaction_hash),
        created_at=op.created_at,
    )


async def _verified_wallet(session: AsyncSession, user: User, address: str) -> str:
    wallet = await users_repo.find_verified_wallet(session, user.id, address, get_network().network)
    if wallet is None:
        raise Forbidden(
            "Connect and verify this wallet on your profile before using it for on-chain actions.",
            code="wallet_not_verified",
        )
    return wallet.public_address


async def _record(
    session: AsyncSession,
    user: User,
    asset: RewardAsset,
    kind: AssetOperationKind,
    *,
    source: str,
    tx_hash: str,
    unsigned_xdr: str,
    fee: int | None,
    expires_in: int,
) -> AssetOperation:
    network = get_network()
    # Supersede this user's earlier unsigned operation of the same kind for the asset.
    await session.execute(
        update(AssetOperation)
        .where(
            AssetOperation.user_id == user.id,
            AssetOperation.asset_id == asset.id,
            AssetOperation.kind == kind,
            AssetOperation.status == AssetOperationStatus.SIGNATURE_REQUIRED,
        )
        .values(
            status=AssetOperationStatus.EXPIRED, failure_reason="Superseded by a newer prepared transaction."
        )
    )
    op = AssetOperation(
        id=uuid.uuid4(),
        user_id=user.id,
        asset_id=asset.id,
        kind=kind,
        status=AssetOperationStatus.SIGNATURE_REQUIRED,
        network=network.network,
        source_address=source,
        transaction_hash=tx_hash,
        unsigned_xdr=unsigned_xdr,
        fee_stroops=fee,
        expires_at=utcnow() + timedelta(seconds=expires_in),
    )
    session.add(op)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict(
            "An identical transaction was prepared moments ago. Please try again in a few seconds."
        ) from exc
    return op


def _prepared(op: AssetOperation, asset: RewardAsset, description: str) -> PreparedAssetOperation:
    network = get_network()
    assert op.unsigned_xdr is not None
    assert op.expires_at is not None
    return PreparedAssetOperation(
        operation=serialize(op, asset),
        unsigned_xdr=op.unsigned_xdr,
        network_passphrase=network.passphrase,
        network=network.network,
        description=description,
        fee_estimate_stroops=str(op.fee_stroops) if op.fee_stroops is not None else None,
        expires_at=op.expires_at,
    )


# --- Trustlines --------------------------------------------------------------------------------------


def _sponsorable_asset(asset: RewardAsset) -> bool:
    """Whether the fee sponsor is allowed to pay for a trustline to this asset (SPONSOR_ALLOWED_ASSETS)."""
    return f"{asset.code}:{asset.issuer}" in set(get_settings().sponsor_allowed_assets)


async def prepare_trustline(
    session: AsyncSession, user: User, asset_id: uuid.UUID, wallet_address: str
) -> PreparedAssetOperation:
    asset = await registry.get_asset(session, asset_id)
    if asset.kind == AssetKind.NATIVE:
        raise ValidationFailed("XLM needs no trustline.", code="trustline_not_required")
    source = await _verified_wallet(session, user, wallet_address)
    if is_contract_address(source):
        raise ValidationFailed(
            f"Contract wallets hold {asset.code} without a trustline.", code="trustline_not_required"
        )
    network = get_network()
    try:
        account = await get_horizon().load_account(source)
    except HorizonUnavailable as exc:
        raise BlockchainError(str(exc)) from exc
    if account is None:
        raise ValidationFailed(
            f"This wallet account does not exist on the network yet. {FRIENDBOT_HINT}",
            code="account_not_found",
        )
    existing = account.balance(asset.identifier)
    if existing is not None:
        raise Conflict(f"This wallet already has a {asset.code} trustline.", code="trustline_exists")
    fee = min(network.base_fee, CLASSIC_MAX_FEE)
    # The platform can pay the network fee (a fee bump on an allow-listed asset), but never the reserve: Stellar
    # requires the account itself to lock 0.5 XLM for the new trustline subentry.
    sponsored = sponsorship.is_enabled() and _sponsorable_asset(asset)
    needed = TRUSTLINE_RESERVE if sponsored else TRUSTLINE_RESERVE + Decimal(fee) / Decimal(10_000_000)
    if account.native_spendable < needed:
        raise ValidationFailed(
            f"A trustline locks 0.5 XLM as reserve. This wallet has "
            f"{display_amount(account.native_spendable, 'XLM')} available."
            + (" BountyFlow pays the network fee." if sponsored else ""),
            code="insufficient_balance",
        )
    tx = (
        TransactionBuilder(Account(source, account.sequence), network.passphrase, base_fee=fee)
        .append_change_trust_op(parse_identifier(asset.identifier).to_stellar())
        .set_timeout(network.tx_timeout_seconds)
        .build()
    )
    op = await _record(
        session,
        user,
        asset,
        AssetOperationKind.TRUSTLINE,
        source=source,
        tx_hash=tx.hash_hex(),
        unsigned_xdr=tx.to_xdr(),
        fee=tx.transaction.fee,
        expires_in=network.tx_timeout_seconds,
    )
    await session.commit()
    return _prepared(
        op, asset, f"Add a {asset.code} trustline so this wallet can hold and receive {asset.code}."
    )


# --- Stellar Asset Contract deployment -------------------------------------------------------------


async def prepare_deploy(
    session: AsyncSession, user: User, asset_id: uuid.UUID, wallet_address: str
) -> PreparedAssetOperation:
    if not has_permission(user, Permission.ASSET_MANAGE):
        raise Forbidden("Only admins can deploy asset contracts.")
    asset = await registry.get_asset(session, asset_id)
    if asset.kind == AssetKind.NATIVE:
        raise InvalidStateTransition("The native XLM contract is part of the network.")
    source = await _verified_wallet(session, user, wallet_address)
    tokens = get_tokens()
    try:
        exists = await tokens.contract_exists(asset.contract_id)
    except ChainUnavailable as exc:
        raise BlockchainError(str(exc)) from exc
    if exists:
        # Somebody else deployed it. Read the contract, then record that in its own short transaction.
        reads = await registry.read_from_chain(asset)
        code = asset.code
        await session.rollback()
        locked = await registry.get_asset(session, asset_id, for_update=True)
        registry.apply_chain_reads(locked, reads)
        await session.commit()
        await registry.invalidate_registry()
        raise Conflict(f"The {code} asset contract is already deployed.", code="contract_exists")
    try:
        prepared = await tokens.prepare_deploy(asset.identifier, source)
    except AccountNotFound as exc:
        raise ValidationFailed(str(exc), code="account_not_found") from exc
    except ContractError as exc:
        raise ValidationFailed(
            exc.message, code="contract_rejected", details={"contract_error": exc.name}
        ) from exc
    except ChainUnavailable as exc:
        raise BlockchainError(str(exc)) from exc
    assert prepared.unsigned_xdr is not None
    op = await _record(
        session,
        user,
        asset,
        AssetOperationKind.DEPLOY_CONTRACT,
        source=source,
        tx_hash=prepared.tx_hash,
        unsigned_xdr=prepared.unsigned_xdr,
        fee=prepared.fee_stroops,
        expires_in=get_network().tx_timeout_seconds,
    )
    await session.commit()
    return _prepared(op, asset, f"Deploy the Stellar Asset Contract for {asset.code} so escrows can hold it.")


# --- Submission and verification ---------------------------------------------------------------------


async def _lock(key: str, ttl: int = 60) -> bool:
    try:
        return bool(await get_redis().set(key, "1", nx=True, ex=ttl))
    except Exception:
        return True  # Redis down: the row lock and the unique hash still prevent double effects


async def _unlock(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception as exc:
        logger.debug("asset_operation_unlock_failed", error=str(exc))


async def _load_pair(
    session: AsyncSession, op_id: uuid.UUID, *, for_update: bool = False
) -> tuple[AssetOperation, RewardAsset]:
    """An operation and its asset in one joined query (never a second round trip per row)."""
    stmt = (
        select(AssetOperation, RewardAsset)
        .join(RewardAsset, RewardAsset.id == AssetOperation.asset_id)
        .where(AssetOperation.id == op_id)
    )
    if for_update:
        # Only the operation row is locked: the asset row is read for its identifier and contract id.
        stmt = stmt.with_for_update(of=AssetOperation).execution_options(populate_existing=True)
    row = (await session.execute(stmt)).first()
    if row is None:
        raise NotFound("Operation not found.")
    return row[0], row[1]


@dataclass(frozen=True)
class _Target:
    """What the network reads need, copied off the rows while they are still loaded.

    Every chain call below runs with no database transaction open, and rolling one back expires every instance
    the session holds: an attribute read afterwards would be a lazy load, which async SQLAlchemy cannot do. So
    the reads work from this plain snapshot, never from an ORM row (``_apply`` writes to freshly locked rows)."""

    kind: AssetOperationKind
    transaction_hash: str
    source_address: str = ""
    identifier: str = ""
    contract_id: str = ""


def _target(op: AssetOperation, asset: RewardAsset | None = None) -> _Target:
    return _Target(
        kind=op.kind,
        transaction_hash=op.transaction_hash,
        source_address=op.source_address,
        identifier=asset.identifier if asset is not None else "",
        contract_id=asset.contract_id if asset is not None else "",
    )


async def _landed(target: _Target) -> bool | None:
    """Whether the network already has a result for this operation (None: it cannot be asked right now)."""
    try:
        if target.kind == AssetOperationKind.TRUSTLINE:
            return await get_horizon().transaction(target.transaction_hash) is not None
        outcome = await get_tokens().outcome(target.transaction_hash)
        return outcome.status in ("SUCCESS", "FAILED")
    except (HorizonUnavailable, ChainUnavailable):
        return None


def _fail(op: AssetOperation, reason: str, code: str | None = None) -> None:
    op.status = AssetOperationStatus.FAILED
    op.failure_reason = reason
    op.result_code = code


@dataclass(frozen=True)
class _ChainReads:
    """Everything the network is asked for before a settlement, read while no row is locked.

    ``effect_present`` is the read-back that makes the operation honest: the trustline is on the account, or the
    asset contract exists. ``outcome`` is the transaction result in the shape fee sponsorship accounts in."""

    outcome: TxOutcome
    effect_present: bool = False
    metadata: TokenMetadata | None = None  # DEPLOY_CONTRACT: the deployed contract's symbol and decimals


def _classic_outcome(result: ClassicResult | None) -> TxOutcome:
    if result is None:
        return TxOutcome(status="NOT_FOUND")
    if result.successful:
        return TxOutcome(status="SUCCESS", ledger=result.ledger, ledger_close_time=utcnow())
    return TxOutcome(
        status="FAILED",
        ledger=result.ledger,
        failure_reason=result.message or "The transaction failed.",
        result_code=result.result_code,
    )


async def _read_trustline(target: _Target) -> _ChainReads:
    horizon = get_horizon()
    outcome = _classic_outcome(await horizon.transaction(target.transaction_hash))
    if outcome.status != "SUCCESS":
        return _ChainReads(outcome)
    account = await horizon.load_account(target.source_address)
    return _ChainReads(
        outcome, effect_present=account is not None and account.balance(target.identifier) is not None
    )


async def _read_deploy(target: _Target) -> _ChainReads:
    tokens = get_tokens()
    outcome = await tokens.outcome(target.transaction_hash)
    if outcome.status != "SUCCESS":
        return _ChainReads(outcome)
    if not await tokens.contract_exists(target.contract_id):
        return _ChainReads(outcome)
    return _ChainReads(outcome, effect_present=True, metadata=await tokens.metadata(target.contract_id))


async def _read_chain(target: _Target) -> _ChainReads:
    if target.kind == AssetOperationKind.TRUSTLINE:
        return await _read_trustline(target)
    return await _read_deploy(target)


def _expired(op: AssetOperation) -> bool:
    return op.expires_at is not None and utcnow() > op.expires_at + EXPIRY_GRACE


def _apply(op: AssetOperation, asset: RewardAsset, reads: _ChainReads) -> None:
    """Writes the verified outcome onto the locked rows. Pure database work: every chain read it needs was made
    by ``_read_chain`` beforehand, and running it twice on an already-settled row changes nothing."""
    outcome = reads.outcome
    if outcome.status in ("PENDING", "NOT_FOUND"):
        if outcome.status == "NOT_FOUND" and _expired(op):
            op.status = AssetOperationStatus.EXPIRED
            op.failure_reason = "The network never included this transaction before it expired."
        return
    op.ledger_sequence = outcome.ledger or op.ledger_sequence
    if outcome.status == "FAILED":
        _fail(op, outcome.failure_reason or "The transaction failed.", outcome.result_code)
        return
    if not reads.effect_present:
        _fail(
            op,
            "The transaction succeeded, but the wallet shows no trustline for this asset."
            if op.kind == AssetOperationKind.TRUSTLINE
            else "The transaction succeeded, but the asset contract was not found on the network.",
        )
        return
    if op.kind == AssetOperationKind.DEPLOY_CONTRACT:
        meta = reads.metadata
        if meta is None or meta.decimals != SAC_DECIMALS:
            _fail(op, "The asset contract does not report Stellar's 7 decimals.")
            return
        asset.symbol = meta.symbol
        asset.decimals = meta.decimals
        asset.contract_status = ContractStatus.DEPLOYED
        asset.verified_at = utcnow()
    op.status = AssetOperationStatus.CONFIRMED
    op.confirmed_at = outcome.ledger_close_time or utcnow()


async def _settle_sponsorship(session: AsyncSession, op: AssetOperation, outcome: TxOutcome) -> None:
    """Mirrors the sponsor's spend onto its row, inside the same transaction as the operation's own result."""
    if op.sponsorship_id is None:
        return
    row = await session.get(SponsoredTransaction, op.sponsorship_id, with_for_update=True)
    if row is not None and row.status == SponsorshipStatus.SUBMITTED:
        await sponsorship.apply_outcome(row, outcome, failure=op.failure_reason)


async def submit(session: AsyncSession, user: User, op_id: uuid.UUID, signed_xdr: str) -> AssetOperationOut:
    """Signed envelope -> network -> verified result.

    Three steps, so no row lock is ever held across a network call: the intent (the operation marked SUBMITTED
    with the exact envelope that will be sent, and the sponsorship row when the platform pays the fee) commits
    first, the transaction is then handed to the network, and the outcome is written in its own transaction."""
    lock = f"{keys.PREFIX}:lock:asset-op:submit:{op_id}"
    if not await _lock(lock):
        raise Conflict("This transaction is already being submitted.")
    try:
        envelope = await _claim_for_submission(session, user, op_id, signed_xdr)
        if envelope is not None:
            await _send_and_record(session, op_id, envelope)
    finally:
        await _unlock(lock)
    # Best-effort immediate verification; the sweep job guarantees it eventually.
    try:
        await verify(session, op_id)
    except (HorizonUnavailable, ChainUnavailable):
        await session.rollback()
    except Exception:
        logger.exception("asset_operation_verification_failed", op_id=str(op_id))
        await session.rollback()
    op, asset = await _load_pair(session, op_id)
    return serialize(op, asset)


async def _claim_for_submission(
    session: AsyncSession, user: User, op_id: uuid.UUID, signed_xdr: str
) -> str | None:
    """Validates the signature and claims the operation for submission, committing the intent. Returns the
    envelope to send, or None when there is nothing to send (already submitted, or expired unsigned)."""
    network = get_network()
    op, _asset = await _load_pair(session, op_id)
    if op.user_id != user.id:
        raise NotFound("Operation not found.")
    if op.status in (AssetOperationStatus.SUBMITTED, AssetOperationStatus.CONFIRMED):
        return op.submitted_xdr if op.status == AssetOperationStatus.SUBMITTED else None
    if op.status != AssetOperationStatus.SIGNATURE_REQUIRED:
        raise InvalidStateTransition(f"This transaction is {op.status.value.lower()}; start again.")
    if op.network != network.network:
        raise InvalidStateTransition("This transaction was prepared for a different network.")
    try:
        verify_signed_envelope(
            signed_xdr,
            expected_hash=op.transaction_hash,
            expected_source=op.source_address,
            network_passphrase=network.passphrase,
        )
    except EnvelopeMismatch as exc:
        raise ValidationFailed(str(exc), code="signature_invalid") from exc
    if op.expires_at and op.expires_at <= utcnow():
        # An earlier submit may have reached the network even though its response was lost.
        target = _target(op)  # read off the row before the rollback expires it
        await session.rollback()  # no lock is held while the network is asked
        landed = await _landed(target)
        if landed is None:
            raise BlockchainError("The network could not be reached to check this transaction.")
        if not landed:
            await _mark_expired(session, op_id)
            raise InvalidStateTransition("The transaction expired before it was signed. Start again.")
        await _mark_submitted(session, user, op_id, signed_xdr, sponsor=False)
        return None  # it is already on the network: verification picks it up
    return await _mark_submitted(session, user, op_id, signed_xdr, sponsor=True)


async def _mark_expired(session: AsyncSession, op_id: uuid.UUID) -> None:
    op, _asset = await _load_pair(session, op_id, for_update=True)
    if op.status == AssetOperationStatus.SIGNATURE_REQUIRED:
        op.status = AssetOperationStatus.EXPIRED
        op.failure_reason = "The transaction expired before it was signed."
    await session.commit()


async def _mark_submitted(
    session: AsyncSession, user: User, op_id: uuid.UUID, signed_xdr: str, *, sponsor: bool
) -> str | None:
    """One transaction: the operation becomes SUBMITTED with the envelope that will be sent, the sponsorship row
    (if the platform pays the fee) and the audit entry all commit together, before anything reaches the network."""
    if sponsor and sponsorship.is_enabled():
        # The sponsor's balance is the one network read the budget check makes: warm its cache before the row is
        # locked, so the transaction below holds its locks over database work only.
        await sponsorship.sponsor_balance()
    op, asset = await _load_pair(session, op_id, for_update=True)
    if op.status != AssetOperationStatus.SIGNATURE_REQUIRED:
        await session.rollback()
        return None if op.status != AssetOperationStatus.SUBMITTED else op.submitted_xdr
    envelope = signed_xdr
    if sponsor:
        # A trustline costs a 0.5 XLM reserve the wallet must hold itself, but the platform can pay its fee
        # (app/blockchain/sponsorship.py, SPONSOR_ALLOWED_ASSETS), so a contributor with almost no XLM can add one.
        submission = await sponsorship.sponsor_envelope(
            session,
            user_id=user.id,
            signed_xdr=signed_xdr,
            purpose=f"asset:{op.kind.value.lower()}",
        )
        envelope = submission.xdr
        if submission.sponsorship is not None:
            await session.flush()  # the row needs its id before the operation references it
            op.sponsorship_id = submission.sponsorship.id
    op.status = AssetOperationStatus.SUBMITTED
    op.submitted_at = utcnow()
    op.submitted_xdr = envelope
    audit.record(
        session,
        actor_id=user.id,
        action="asset.operation_submitted",
        entity_type="asset_operation",
        entity_id=op.id,
        metadata={
            "kind": op.kind.value,
            "asset": asset.identifier,
            "hash": op.transaction_hash,
            "sponsored": op.sponsorship_id is not None,
        },
        is_public=False,
    )
    await session.commit()
    return envelope


async def _send_and_record(session: AsyncSession, op_id: uuid.UUID, envelope: str) -> None:
    """Hands the envelope to the network (no locks held), then records a rejection in its own transaction. A
    success is left to verification, which reads the effect back from the chain before confirming anything."""
    op, _asset = await _load_pair(session, op_id)
    kind, tx_hash = op.kind, op.transaction_hash
    await session.rollback()
    outcome: TxOutcome | None = None
    if kind == AssetOperationKind.TRUSTLINE:
        try:
            outcome = _classic_outcome(await get_horizon().submit(envelope))
        except HorizonUnavailable:
            logger.warning("trustline_submit_outcome_unknown", op_id=str(op_id))
            return
    else:
        try:
            submitted = await get_tokens().submit(envelope, tx_hash)
        except ChainRejected as exc:
            outcome = TxOutcome(status="FAILED", failure_reason=str(exc), result_code=exc.code)
        except ChainUnavailable as exc:
            raise BlockchainError(str(exc)) from exc
        else:
            if submitted != tx_hash and not sponsorship.is_fee_bump(envelope):
                raise BlockchainError("The network returned an unexpected transaction hash.")
    if outcome is None or outcome.status != "FAILED":
        return
    locked, _asset = await _load_pair(session, op_id, for_update=True)
    if locked.status == AssetOperationStatus.SUBMITTED:
        _fail(locked, outcome.failure_reason or "The transaction failed.", outcome.result_code)
        await _settle_sponsorship(session, locked, outcome)
    await session.commit()


async def verify(session: AsyncSession, op_id: uuid.UUID) -> AssetOperationStatus:
    """Idempotently settles a SUBMITTED operation from network state: the chain is read first, then one
    transaction locks the rows and writes the result."""
    lock = f"{keys.PREFIX}:lock:asset-op:verify:{op_id}"
    if not await _lock(lock):
        return AssetOperationStatus.SUBMITTED
    try:
        op, asset = await _load_pair(session, op_id)
        if op.status != AssetOperationStatus.SUBMITTED:
            status = op.status
            await session.rollback()
            return status
        target = _target(op, asset)  # read off the rows before the rollback expires them
        await session.rollback()  # the reads below are network I/O: no transaction stays open across them
        reads = await _read_chain(target)

        locked, asset = await _load_pair(session, op_id, for_update=True)
        if locked.status != AssetOperationStatus.SUBMITTED:
            status = locked.status
            await session.rollback()
            return status
        _apply(locked, asset, reads)
        if locked.status != AssetOperationStatus.SUBMITTED:
            await _settle_sponsorship(session, locked, reads.outcome)
        if locked.status == AssetOperationStatus.CONFIRMED:
            audit.record(
                session,
                actor_id=locked.user_id,
                action="asset.trustline_added"
                if locked.kind == AssetOperationKind.TRUSTLINE
                else "asset.contract_deployed",
                entity_type="asset_operation",
                entity_id=locked.id,
                metadata={
                    "asset": asset.identifier,
                    "hash": locked.transaction_hash,
                    "address": locked.source_address,
                },
                is_public=False,
            )
        settled = locked.status
        kind, address, identifier = locked.kind, locked.source_address, asset.identifier
        await session.commit()
        if settled == AssetOperationStatus.CONFIRMED:
            if kind == AssetOperationKind.TRUSTLINE:
                await invalidate_trustline(address, identifier)
            else:
                await registry.invalidate_registry()
        return settled
    finally:
        await _unlock(lock)


async def get_operation(session: AsyncSession, user: User, op_id: uuid.UUID) -> AssetOperationOut:
    op, asset = await _load_pair(session, op_id)
    if op.user_id != user.id and not has_permission(user, Permission.ASSET_MANAGE):
        raise NotFound("Operation not found.")
    if op.status == AssetOperationStatus.SUBMITTED:
        try:
            await verify(session, op_id)
        except (HorizonUnavailable, ChainUnavailable):
            await session.rollback()
        op, asset = await _load_pair(session, op_id)
    return serialize(op, asset)


async def sweep(session: AsyncSession, limit: int = 50) -> int:
    """Worker job: settles SUBMITTED operations and expires stale unsigned ones (after asking the network, since a
    submission whose response was lost can still land)."""
    now = utcnow()
    stale = (
        (
            await session.scalars(
                select(AssetOperation)
                .where(
                    AssetOperation.status == AssetOperationStatus.SIGNATURE_REQUIRED,
                    AssetOperation.expires_at < now,
                )
                .limit(limit)
            )
        )
        .unique()
        .all()
    )
    targets = [(op.id, _target(op)) for op in stale]  # read off the rows before the rollback expires them
    await session.rollback()  # the reads below are network I/O: nothing is locked across them
    landings = [(op_id, await _landed(target)) for op_id, target in targets]
    for op_id, landed in landings:
        if landed is None:
            continue  # the network is unreachable: decide on a later run
        locked = await session.scalar(
            select(AssetOperation)
            .where(AssetOperation.id == op_id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if locked is None or locked.status != AssetOperationStatus.SIGNATURE_REQUIRED:
            continue
        if landed:
            locked.status = AssetOperationStatus.SUBMITTED
            locked.submitted_at = locked.submitted_at or now
        else:
            locked.status = AssetOperationStatus.EXPIRED
            locked.failure_reason = "Expired before it was signed."
    await session.commit()
    pending = (
        await session.scalars(
            select(AssetOperation.id)
            .where(AssetOperation.status == AssetOperationStatus.SUBMITTED)
            .order_by(AssetOperation.submitted_at)
            .limit(limit)
        )
    ).all()
    processed = 0
    for op_id in pending:
        try:
            await verify(session, op_id)
            processed += 1
        except (HorizonUnavailable, ChainUnavailable) as exc:
            logger.warning("asset_operation_verification_deferred", op_id=str(op_id), error=str(exc))
            await session.rollback()
            break
        except Exception:
            logger.exception("asset_operation_sweep_failed", op_id=str(op_id))
            await session.rollback()
    return processed + len(landings)
