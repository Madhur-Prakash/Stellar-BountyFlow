"""Guards that block chain actions which would fail on-chain because of an asset, with a specific message.

* Before funding: the requester's wallet must hold the escrow asset with enough spendable balance (Horizon for
  G-addresses, the SAC ``balance`` for C-addresses).
* Before a contributor is assigned (off-chain acceptance and the on-chain ``assign``) and again before every
  action that pays them — ``release``, ``release_milestone``, ``batch_release``, ``claim`` and a dispute vote
  that pays — the receiving wallet must be able to receive the asset. A SAC transfer of a classic asset to a
  G-address without a trustline (or with an unauthorized one) fails; XLM needs none, and a contract address
  (a passkey smart wallet, ``C…``) holds SAC balances in contract storage, so it needs none either. The
  contributor is notified so they can add the trustline.
* A batch payout pays every leg atomically, so all of its destinations are checked *before* it is signed and
  the refusal names the wallet that cannot receive.

When Horizon cannot be reached the state is UNKNOWN and nothing is blocked: the transaction simulation and the
contract still refuse anything that cannot succeed, so an outage only loses the friendlier message.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.assets import NATIVE, is_contract_address, parse_identifier
from app.blockchain.config import get_network
from app.blockchain.horizon import AccountState, HorizonUnavailable, get_horizon
from app.blockchain.tokens import get_tokens
from app.blockchain.transactions import ChainUnavailable
from app.cache import keys
from app.cache.redis import get_redis
from app.core.exceptions import ValidationFailed
from app.core.logging import get_logger
from app.core.money import ZERO, display_amount
from app.db.session import session_scope
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.applications.models import BountyAssignment
from app.modules.assets import service as registry
from app.modules.assets.schemas import TrustlineState
from app.modules.bounties.models import Bounty
from app.modules.payments.models import TxType
from app.modules.users import repository as users_repo
from app.modules.users.models import User

logger = get_logger(__name__)

TRUSTLINE_CACHE_TTL = 20
NOTICE_TTL = 6 * 3600  # one "add a trustline" notice per contributor, bounty and stage every 6 hours
FRIENDBOT_HINT = "On Testnet, fund it with Friendbot first."
# Horizon reads for one batch run together, but never more than this many at once.
_CONCURRENCY = 8

# Actions whose destination receives the reward, so the wallet must hold a trustline for the escrow's asset.
# ASSIGN is included: it binds the wallet that ``release`` will later pay.
_RECEIVING_TX_TYPES = frozenset(
    {
        TxType.ASSIGN,
        TxType.PAYOUT,
        TxType.MILESTONE_PAYOUT,
        TxType.CLAIM,
    }
)


def _state_key(address: str, identifier: str) -> str:
    return f"{keys.PREFIX}:trustline:{get_network().network}:{address}:{identifier}"


async def invalidate_trustline(address: str, identifier: str) -> None:
    try:
        await get_redis().delete(_state_key(address, identifier))
    except Exception as exc:
        logger.debug("trustline_cache_clear_failed", error=str(exc))


def state_from_account(
    account: AccountState | None, identifier: str
) -> tuple[TrustlineState, Decimal | None]:
    """Pure: the trustline state of ``identifier`` for a loaded (G-address) account."""
    ref = parse_identifier(identifier)
    if account is None:
        return TrustlineState.ACCOUNT_MISSING, None
    if ref.is_native:
        return TrustlineState.NOT_REQUIRED, account.native_spendable
    if account.address == ref.issuer:
        return TrustlineState.NOT_REQUIRED, None  # an issuer sends and receives its own asset without one
    balance = account.balance(identifier)
    if balance is None:
        return TrustlineState.MISSING, None
    if not balance.is_authorized:
        return TrustlineState.UNAUTHORIZED, balance.spendable
    return TrustlineState.ACTIVE, balance.spendable


async def trustline_state(identifier: str, address: str) -> tuple[TrustlineState, Decimal | None]:
    """Whether ``address`` can receive ``identifier``, and its spendable balance of it when known."""
    ref = parse_identifier(identifier)
    if ref.is_native or is_contract_address(address) or address == ref.issuer:
        return TrustlineState.NOT_REQUIRED, None
    key = _state_key(address, identifier)
    try:
        cached = await get_redis().get(key)
    except Exception:
        cached = None
    if cached:
        data = json.loads(cached)
        return TrustlineState(data["state"]), Decimal(data["balance"]) if data.get("balance") else None
    try:
        account = await get_horizon().load_account(address)
    except HorizonUnavailable as exc:
        logger.warning("trustline_check_unavailable", address=address, identifier=identifier, error=str(exc))
        return TrustlineState.UNKNOWN, None
    state, balance = state_from_account(account, identifier)
    try:
        payload = {"state": state.value, "balance": str(balance) if balance is not None else None}
        await get_redis().set(key, json.dumps(payload), ex=TRUSTLINE_CACHE_TTL)
    except Exception as exc:
        logger.debug("trustline_cache_write_failed", error=str(exc))
    return state, balance


# --- Funding ----------------------------------------------------------------------------------


async def spendable_balance(identifier: str, address: str) -> tuple[TrustlineState, Decimal | None]:
    """(trustline state, spendable balance) of ``identifier`` in the funding wallet. Uncached: it is read right
    before a deposit is prepared."""
    ref = parse_identifier(identifier)
    if is_contract_address(address):
        try:
            return TrustlineState.NOT_REQUIRED, await get_tokens().contract_balance(identifier, address)
        except ChainUnavailable as exc:
            logger.warning("contract_balance_unavailable", address=address, error=str(exc))
            return TrustlineState.UNKNOWN, None
    try:
        account = await get_horizon().load_account(address)
    except HorizonUnavailable as exc:
        logger.warning("funding_check_unavailable", address=address, error=str(exc))
        return TrustlineState.UNKNOWN, None
    if account is None:
        return TrustlineState.ACCOUNT_MISSING, None
    if ref.is_native:
        return TrustlineState.NOT_REQUIRED, account.native_spendable
    return state_from_account(account, identifier)


def funding_problem(
    identifier: str, state: TrustlineState, available: Decimal | None, required: Decimal
) -> tuple[str, str] | None:
    """(error code, message) when a deposit of ``required`` cannot succeed from this wallet; None when it can
    (or when the balance is unknown)."""
    code = parse_identifier(identifier).code
    if state == TrustlineState.ACCOUNT_MISSING:
        return "account_not_found", f"This wallet account does not exist on the network yet. {FRIENDBOT_HINT}"
    if state == TrustlineState.MISSING:
        return (
            "trustline_missing",
            f"This wallet can't hold {code} yet. Add a {code} trustline, then add {code} to the wallet.",
        )
    if state == TrustlineState.UNAUTHORIZED:
        return (
            "trustline_unauthorized",
            f"The {code} issuer has not authorized this wallet's trustline yet, so it can't send {code}.",
        )
    if available is not None and available < required:
        return (
            "insufficient_balance",
            f"This wallet has {display_amount(available, code)} available, less than the "
            f"{display_amount(required, code)} this deposit needs.",
        )
    return None


async def ensure_can_fund(identifier: str, address: str, amount: Decimal) -> None:
    state, available = await spendable_balance(identifier, address)
    problem = funding_problem(identifier, state, available, amount)
    if problem:
        code, message = problem
        raise ValidationFailed(
            message,
            code=code,
            details={"asset": identifier, "address": address, "required": str(amount), "stage": "funding"},
        )


# --- Receiving ---------------------------------------------------------------------------------


def receive_message(name: str, code: str, state: TrustlineState, *, self_service: bool = False) -> str:
    """Why a wallet cannot receive the asset. ``self_service``: the signer is the contributor themselves
    (a claim), so the message addresses them directly."""
    if self_service:
        if state == TrustlineState.UNAUTHORIZED:
            return f"The {code} issuer has not authorized your trustline yet, so your wallet can't receive {code}."
        if state == TrustlineState.ACCOUNT_MISSING:
            return f"Your wallet account doesn't exist on the network yet, so it can't receive {code}."
        if state == TrustlineState.NO_WALLET:
            return f"Verify a wallet before claiming {code}."
        return f"Your wallet can't receive {code} yet. Add a {code} trustline, then claim."
    if state == TrustlineState.UNAUTHORIZED:
        return f"{name}'s {code} trustline is not authorized by the issuer yet, so their wallet can't receive {code}."
    if state == TrustlineState.ACCOUNT_MISSING:
        return f"{name}'s wallet account doesn't exist on the network yet, so it can't receive {code}."
    if state == TrustlineState.NO_WALLET:
        return f"{name} has no verified wallet yet, so they can't receive {code}."
    return f"{name}'s wallet can't receive {code} yet. They need to add a {code} trustline."


async def notify_trustline_required(
    bounty: Bounty, contributor_id: uuid.UUID, identifier: str, stage: str, actor_id: uuid.UUID | None
) -> None:
    """Tells the contributor to add a trustline (in its own transaction: the blocked request is rolled back).
    At most one notice per contributor, bounty and stage every few hours."""
    dedupe = f"{keys.PREFIX}:trustline-notice:{bounty.id}:{contributor_id}:{stage}"
    try:
        if not await get_redis().set(dedupe, "1", nx=True, ex=NOTICE_TTL):
            return
    except Exception as exc:
        logger.debug("trustline_notice_dedupe_unavailable", error=str(exc))
    ref = parse_identifier(identifier)
    try:
        async with session_scope() as session:
            add_event(
                session,
                event_type=EventType.ASSET_TRUSTLINE_REQUIRED,
                aggregate_type="bounty",
                aggregate_id=bounty.id,
                actor_id=actor_id,
                payload={
                    "bounty_id": bounty.id,
                    "requester_id": bounty.requester_id,
                    "contributor_id": contributor_id,
                    "title": bounty.title,
                    "asset_code": ref.code,
                    "asset": ref.identifier,
                    "stage": stage,
                },
            )
    except Exception:
        logger.exception("trustline_notice_failed", bounty_id=str(bounty.id))


async def ensure_can_receive(
    bounty: Bounty,
    identifier: str,
    contributor: User,
    address: str | None,
    *,
    stage: str,
    actor_id: uuid.UUID | None,
    self_service: bool = False,
) -> None:
    """Blocks assigning or paying ``contributor`` when their wallet cannot receive the bounty's asset."""
    ref = parse_identifier(identifier)
    if ref.is_native:
        return
    state = TrustlineState.NO_WALLET if address is None else (await trustline_state(identifier, address))[0]
    if state.can_receive:
        return
    await notify_trustline_required(bounty, contributor.id, identifier, stage, actor_id)
    raise ValidationFailed(
        receive_message(contributor.display_name, ref.code, state, self_service=self_service),
        code="trustline_missing",
        details={
            "asset": identifier,
            "address": address,
            "contributor_id": str(contributor.id),
            "state": state.value,
            "stage": stage,
        },
    )


async def ensure_contributor_can_receive(
    session: AsyncSession, bounty: Bounty, contributor_id: uuid.UUID, *, actor_id: uuid.UUID | None
) -> None:
    """Off-chain acceptance: the contributor's payout wallet must be able to receive the reward asset."""
    if bounty.reward_asset_identifier in (None, NATIVE):
        return
    contributor = await session.get(User, contributor_id)
    if contributor is None:
        return
    wallet = await users_repo.primary_wallet(session, contributor_id, get_network().network)
    await ensure_can_receive(
        bounty,
        bounty.reward_asset_identifier,
        contributor,
        wallet.public_address if wallet else None,
        stage="assignment",
        actor_id=actor_id,
    )


async def ensure_batch_can_receive(
    session: AsyncSession,
    bounty: Bounty,
    identifier: str,
    legs: Sequence[Mapping[str, Any]],
    *,
    actor_id: uuid.UUID | None,
) -> None:
    """Every leg of a batch payout, checked before the batch is signed.

    ``batch_release`` pays all of its legs atomically, so one contributor without a trustline fails the whole
    transaction on-chain. Each destination is checked up front and the refusal names the wallet that cannot
    receive, so the requester knows which leg to drop. The contributors are loaded with one join and their
    Horizon reads overlap; distinct addresses are read once."""
    ref = parse_identifier(identifier)
    if ref.is_native or not legs:
        return
    assignment_ids = [uuid.UUID(str(leg["assignment_id"])) for leg in legs if leg.get("assignment_id")]
    people = {
        assignment_id: (contributor_id, display_name)
        for assignment_id, contributor_id, display_name in (
            await session.execute(
                select(BountyAssignment.id, User.id, User.display_name)
                .join(User, User.id == BountyAssignment.contributor_id)
                .where(BountyAssignment.id.in_(assignment_ids))
            )
        ).all()
    }
    addresses = list(dict.fromkeys(str(leg["contributor"]) for leg in legs if leg.get("contributor")))
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def state_of(address: str) -> tuple[str, TrustlineState]:
        async with semaphore:
            return address, (await trustline_state(identifier, address))[0]

    states = dict(await asyncio.gather(*(state_of(address) for address in addresses)))
    for leg in legs:
        address = str(leg.get("contributor") or "")
        state = states.get(address, TrustlineState.NO_WALLET)
        if state.can_receive:
            continue
        assignment_id = uuid.UUID(str(leg["assignment_id"])) if leg.get("assignment_id") else None
        contributor_id, name = (
            people.get(assignment_id, (None, "This contributor"))
            if assignment_id
            else (None, "This contributor")
        )
        if contributor_id is not None:
            await notify_trustline_required(bounty, contributor_id, identifier, "payout", actor_id)
        raise ValidationFailed(
            f"{receive_message(name, ref.code, state)} Remove that payment from the batch, or wait until "
            "the trustline is added: a batch pays every contributor in one transaction.",
            code="trustline_missing",
            details={
                "asset": identifier,
                "address": address,
                "contributor_id": str(contributor_id) if contributor_id else None,
                "state": state.value,
                "stage": "batch_payout",
            },
        )


async def check_before_prepare(
    session: AsyncSession,
    bounty: Bounty,
    identifier: str,
    tx_type: TxType,
    *,
    source: str,
    amount: Decimal | None,
    destination: str | None,
    assignment_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    legs: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Called by the payments service right before a chain action is built and simulated."""
    if tx_type in (TxType.ESCROW_CREATE, TxType.ESCROW_FUND):
        await registry.require_fundable(session, identifier)
        if amount is not None and amount > ZERO:
            await ensure_can_fund(identifier, source, amount)
        return
    if tx_type == TxType.BATCH_PAYOUT:
        await ensure_batch_can_receive(session, bounty, identifier, legs or [], actor_id=actor_id)
        return
    # Every action that moves the reward to a contributor, plus ASSIGN, which binds the wallet that will be
    # paid later. A dispute decision that pays nothing (releasing the claim) needs no trustline.
    paying = tx_type in _RECEIVING_TX_TYPES or (
        tx_type in (TxType.DISPUTE_RESOLVE, TxType.DISPUTE_VOTE) and amount is not None
    )
    if paying and destination and assignment_id:
        contributor_id = await session.scalar(
            select(BountyAssignment.contributor_id).where(BountyAssignment.id == assignment_id)
        )
        contributor = await session.get(User, contributor_id) if contributor_id else None
        if contributor is not None:
            stage = "assignment" if tx_type == TxType.ASSIGN else "payout"
            await ensure_can_receive(
                bounty,
                identifier,
                contributor,
                destination,
                stage=stage,
                actor_id=actor_id,
                self_service=actor_id == contributor.id,
            )
        return
    if tx_type == TxType.REFUND and destination and amount is not None and amount > ZERO:
        ref = parse_identifier(identifier)
        state, _ = await trustline_state(identifier, destination)
        if not state.can_receive:
            raise ValidationFailed(
                f"Your wallet can't receive {ref.code} right now. Add a {ref.code} trustline, then refund.",
                code="trustline_missing",
                details={
                    "asset": identifier,
                    "address": destination,
                    "state": state.value,
                    "stage": "refund",
                },
            )
