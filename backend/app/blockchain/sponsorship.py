"""Fee sponsorship: the platform sponsor account pays network fees for eligible transactions.

Two mechanisms, both recorded in ``sponsored_transactions``:

* **Fee bump.** A contributor-side call the user signed (e.g. ``consent_cancel``, ``raise_dispute``) is sent
  inside a ``FeeBumpTransaction`` whose fee source is the sponsor. The inner transaction is exactly what the
  user signed, so its hash (the one BountyFlow tracks) is unchanged; the network charges the sponsor.
* **Relay.** A smart wallet (``C...``) cannot be a transaction source. Its invocation is prepared with the
  sponsor as the source; the wallet signs only its authorization entries, which are checked here against what
  was prepared and then re-simulated into a sponsor-signed envelope (``StellarAdapter.relay``).

Policy (every check fails closed; a refused fee bump falls back to the user paying their own fee):

* a sponsor key is configured (``STELLAR_SPONSOR_SECRET``) and its balance is above the stop threshold;
* the call targets the configured escrow contract or ``SPONSOR_ALLOWED_CONTRACTS``;
* fee bumps only for ``SPONSOR_ALLOWED_FUNCTIONS`` called by someone other than the bounty's requester, or a
  trustline (``change_trust``) to an asset in ``SPONSOR_ALLOWED_ASSETS``;
* the fee is at most ``SPONSOR_MAX_FEE_STROOPS``;
* per user and UTC day, at most ``SPONSOR_DAILY_TX_LIMIT`` transactions and ``SPONSOR_DAILY_FEE_LIMIT_STROOPS``
  (counted from ``sponsored_transactions`` under a per-user advisory lock, so Redis is not needed for it).

The sponsor never authorizes anything but the envelope: relayed transactions whose authorization entries would
use the source account's authority are refused.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import (
    Address,
    ChangeTrust,
    FeeBumpTransactionEnvelope,
    InvokeHostFunction,
    Keypair,
    TransactionBuilder,
    TransactionEnvelope,
)
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.auth import _get_address_credentials

from app.blockchain.config import get_network
from app.blockchain.soroban import ContractError
from app.blockchain.transactions import (
    ChainUnavailable,
    TxOutcome,
    envelope_hashes,
    get_adapter,
    is_contract_address,
)
from app.blockchain.verification import EnvelopeMismatch, verify_signed_envelope
from app.cache.keys import PREFIX
from app.cache.redis import cache_get_json, cache_set_json
from app.core.config import get_settings
from app.core.exceptions import BlockchainError, ValidationFailed
from app.core.logging import get_logger
from app.core.money import from_stroops
from app.core.security import utcnow
from app.modules.bounties.models import Bounty
from app.modules.payments.models import BlockchainTransaction, BountyEscrow
from app.modules.wallets.models import SponsoredTransaction, SponsorshipKind, SponsorshipStatus

logger = get_logger(__name__)

STROOPS_PER_XLM = 10_000_000
_BALANCE_CACHE_TTL = 30


@lru_cache(maxsize=4)
def _keypair(secret: str) -> Keypair:
    return Keypair.from_secret(secret)


def sponsor_keypair() -> Keypair | None:
    """The platform sponsor, or None when sponsorship is switched off (no key configured)."""
    secret = get_settings().stellar_sponsor_secret
    if not secret:
        return None
    try:
        return _keypair(secret.strip())
    except Exception:
        logger.error("sponsor_secret_invalid")
        return None


def is_enabled() -> bool:
    return sponsor_keypair() is not None


def allowed_contracts() -> set[str]:
    network = get_network()
    contracts = set(get_settings().sponsor_allowed_contracts)
    if network.contract_id:
        contracts.add(network.contract_id)
    return contracts


def _allowed_assets() -> set[tuple[str, str]]:
    assets: set[tuple[str, str]] = set()
    for item in get_settings().sponsor_allowed_assets:
        code, _, issuer = item.partition(":")
        if code and issuer:
            assets.add((code.strip(), issuer.strip()))
    return assets


# --- Balance ---------------------------------------------------------------------------------------------


def _balance_key(address: str) -> str:
    return f"{PREFIX}:sponsor:balance:{address}"


async def sponsor_balance(*, fresh: bool = False) -> int | None:
    """The sponsor's XLM balance in stroops (cached for a few seconds), None if unknown or not configured."""
    sponsor = sponsor_keypair()
    if sponsor is None:
        return None
    if not fresh:
        cached = await cache_get_json(_balance_key(sponsor.public_key))
        if isinstance(cached, int):
            return cached
    try:
        balance = await get_adapter().native_balance(sponsor.public_key)
    except ChainUnavailable:
        return None
    if balance is not None:
        await cache_set_json(_balance_key(sponsor.public_key), balance, _BALANCE_CACHE_TTL)
    return balance


# --- Policy ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    sponsored: bool
    reason: str | None = None  # why not, when refused (logged and shown to staff)


_REFUSALS = {
    "disabled": "Fee sponsorship is not configured.",
    "contract": "The call is not to a sponsored contract.",
    "function": "Only contributor-side calls are sponsored.",
    "requester": "Requester transactions are not sponsored.",
    "operation": "The transaction contains operations that are not sponsored.",
    "max_fee": "The network fee is above the sponsorship limit.",
    "daily_tx": "The daily limit of sponsored transactions is reached.",
    "daily_fee": "The daily sponsored fee budget is reached.",
    "balance": "The sponsor account balance is too low.",
}


def refusal_message(reason: str | None) -> str:
    return _REFUSALS.get(reason or "", "The transaction is not eligible for fee sponsorship.")


def day_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def usage_today(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """(transactions, fee budget in stroops) sponsored for the user since 00:00 UTC."""
    row = (
        await session.execute(
            select(
                func.count(SponsoredTransaction.id),
                func.coalesce(
                    func.sum(
                        func.coalesce(
                            SponsoredTransaction.fee_charged_stroops, SponsoredTransaction.max_fee_stroops
                        )
                    ),
                    0,
                ),
            ).where(SponsoredTransaction.user_id == user_id, SponsoredTransaction.created_at >= day_start())
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0)


async def _lock_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Serializes the daily-cap check and the insert of a user's sponsored rows until the transaction ends."""
    key = int.from_bytes(user_id.bytes[:8], "big", signed=True) ^ 0x5B0_5503
    await session.execute(select(func.pg_advisory_xact_lock(key)))


async def check_budget(session: AsyncSession, user_id: uuid.UUID | None, fee: int, *, lock: bool) -> Decision:
    """Fee limit, sponsor balance and the user's daily caps for sponsoring `fee` stroops."""
    settings = get_settings()
    if fee > settings.sponsor_max_fee_stroops:
        return Decision(False, "max_fee")
    balance = await sponsor_balance()
    if balance is not None and balance < settings.sponsor_min_balance_xlm * STROOPS_PER_XLM + fee:
        return Decision(False, "balance")
    if user_id is not None:
        if lock:
            await _lock_user(session, user_id)
        count, spent = await usage_today(session, user_id)
        if count >= settings.sponsor_daily_tx_limit:
            return Decision(False, "daily_tx")
        if spent + fee > settings.sponsor_daily_fee_limit_stroops:
            return Decision(False, "daily_fee")
    return Decision(True)


async def _bounty_context(
    session: AsyncSession, tx: BlockchainTransaction
) -> tuple[uuid.UUID | None, str | None]:
    """One join for both policy questions: whose bounty it is, and which escrow contract it runs on."""
    if tx.bounty_id is None:
        return None, None
    row = (
        await session.execute(
            select(Bounty.requester_id, BountyEscrow.contract_id)
            .outerjoin(BountyEscrow, BountyEscrow.bounty_id == Bounty.id)
            .where(Bounty.id == tx.bounty_id)
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


async def evaluate(session: AsyncSession, tx: BlockchainTransaction, *, lock: bool = False) -> Decision:
    """Whether the platform pays this prepared transaction's network fee (prepare time: a preview; submit time,
    with ``lock``: the binding decision).

    A transaction's contract id and function name are server-set at prepare time, never client supplied, so an
    escrow still running an older BountyFlow contract (``bounty_escrows.contract_id``) is sponsored too."""
    if not is_enabled():
        return Decision(False, "disabled")
    requester_id, escrow_contract = await _bounty_context(session, tx)
    if tx.contract_id not in allowed_contracts() and tx.contract_id != escrow_contract:
        return Decision(False, "contract")
    fee = int(tx.fee_stroops or 0)
    if is_contract_address(tx.source_address):
        # Smart wallets can only transact through the sponsor, for any call to an allowed contract.
        return await check_budget(session, tx.user_id, fee, lock=lock)
    if tx.function_name not in set(get_settings().sponsor_allowed_functions):
        return Decision(False, "function")
    if requester_id is None or requester_id == tx.user_id:
        return Decision(False, "requester")
    # A fee bump bids for one more "operation" (the bump itself) at the inner transaction's inclusion fee.
    return await check_budget(session, tx.user_id, fee + get_network().base_fee, lock=lock)


# --- Submission --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Submission:
    """What to send for a prepared transaction: the user's envelope, a sponsor fee bump around it, or the
    sponsor-signed relay of a smart wallet's authorization."""

    xdr: str
    sponsorship: SponsoredTransaction | None = None


async def existing_record(session: AsyncSession, envelope_hash: str) -> SponsoredTransaction | None:
    """The row already written for this envelope, if any. ``(network, envelope_hash)`` is unique, so a retry (or
    a concurrent submit that slipped past the Redis lock) reuses it instead of raising on the constraint."""
    return await session.scalar(
        select(SponsoredTransaction).where(
            SponsoredTransaction.network == get_network().network,
            SponsoredTransaction.envelope_hash == envelope_hash,
        )
    )


def _record(
    session: AsyncSession,
    tx: BlockchainTransaction | None,
    *,
    kind: SponsorshipKind,
    purpose: str,
    user_id: uuid.UUID | None,
    source: str | None,
    envelope_hash: str,
    inner_hash: str | None,
    max_fee: int,
    contract_id: str | None,
    function_name: str | None,
    passkey_wallet_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    envelope_xdr: str | None = None,
) -> SponsoredTransaction:
    sponsor = sponsor_keypair()
    assert sponsor is not None
    row = SponsoredTransaction(
        id=uuid.uuid4(),
        user_id=user_id,
        blockchain_transaction_id=tx.id if tx is not None else None,
        passkey_wallet_id=passkey_wallet_id,
        kind=kind,
        purpose=purpose[:40],
        network=get_network().network,
        sponsor_address=sponsor.public_key,
        source_address=source,
        inner_hash=inner_hash,
        envelope_hash=envelope_hash,
        contract_id=contract_id,
        function_name=function_name,
        max_fee_stroops=max_fee,
        status=SponsorshipStatus.SUBMITTED,
        details=details or {},
    )
    session.add(row)
    if tx is not None:
        tx.verification_metadata = {
            **(tx.verification_metadata or {}),
            "sponsorship": {
                "id": str(row.id),
                "kind": kind.value,
                "sponsor": sponsor.public_key,
                "envelope_hash": envelope_hash,
                # Kept so a retry after a lost response re-sends the identical envelope.
                "envelope_xdr": envelope_xdr,
            },
        }
    return row


def fee_bump(signed_xdr: str) -> tuple[str, str, int]:
    """Wraps a signed transaction in a sponsor-signed fee bump: ``(xdr, fee bump hash, max fee)``."""
    sponsor = sponsor_keypair()
    assert sponsor is not None
    network = get_network()
    inner = TransactionEnvelope.from_xdr(signed_xdr, network.passphrase)
    resource_fee = (
        int(inner.transaction.soroban_data.resource_fee.int64) if inner.transaction.soroban_data else 0
    )
    operations = len(inner.transaction.operations)
    inner_base_fee = -(-(inner.transaction.fee - resource_fee) // operations)
    bump = TransactionBuilder.build_fee_bump_transaction(
        sponsor.public_key, max(inner_base_fee, network.base_fee), inner, network.passphrase
    )
    bump.sign(sponsor)
    return bump.to_xdr(), bump.hash_hex(), int(bump.transaction.fee)


async def prepare_submission(session: AsyncSession, tx: BlockchainTransaction, signed: str) -> Submission:
    """Checks what the wallet returned for a prepared transaction and decides what goes to the network.

    For an account wallet (``G...``) the signed envelope must be exactly the prepared transaction with a valid
    signature from the source (raises EnvelopeMismatch otherwise); an eligible one is wrapped in a fee bump.
    For a smart wallet (``C...``) see ``_relay``."""
    network = get_network()
    if is_contract_address(tx.source_address):
        return await _relay(session, tx, signed)
    verify_signed_envelope(
        signed,
        expected_hash=tx.transaction_hash or "",
        expected_source=tx.source_address or "",
        network_passphrase=network.passphrase,
    )
    previous = (tx.verification_metadata or {}).get("sponsorship")
    if previous and previous.get("envelope_xdr"):
        return Submission(xdr=str(previous["envelope_xdr"]))
    decision = await evaluate(session, tx, lock=True)
    if not decision.sponsored:
        if decision.reason not in (None, "disabled", "contract", "function", "requester"):
            logger.info("sponsorship_refused", tx_id=str(tx.id), reason=decision.reason)
        return Submission(xdr=signed)
    xdr, bump_hash, max_fee = fee_bump(signed)
    already = await existing_record(session, bump_hash)
    if already is not None:
        return Submission(xdr=xdr, sponsorship=already)
    row = _record(
        session,
        tx,
        kind=SponsorshipKind.FEE_BUMP,
        purpose=str((tx.verification_metadata or {}).get("action") or tx.transaction_type.value),
        user_id=tx.user_id,
        source=tx.source_address,
        envelope_hash=bump_hash,
        inner_hash=tx.transaction_hash,
        max_fee=max_fee,
        contract_id=tx.contract_id,
        function_name=tx.function_name,
        envelope_xdr=xdr,
    )
    # Durable before sending: the sponsor's spend is recorded even if the response is lost.
    await session.commit()
    return Submission(xdr=xdr, sponsorship=row)


def _single_invocation(envelope: TransactionEnvelope) -> InvokeHostFunction:
    operations = envelope.transaction.operations
    if len(operations) != 1 or not isinstance(operations[0], InvokeHostFunction):
        raise EnvelopeMismatch("The signed transaction must contain exactly the prepared contract call.")
    return operations[0]


def _check_signed_authorization(
    prepared: InvokeHostFunction, signed: InvokeHostFunction, wallet: str
) -> list[stellar_xdr.SorobanAuthorizationEntry]:
    """The wallet may only add its signatures (and choose their expiration) to the entries that were
    prepared: same call, same authorized invocation trees, same addresses and nonces."""
    if prepared.host_function.to_xdr() != signed.host_function.to_xdr():
        raise EnvelopeMismatch("The signed call does not match the prepared transaction.")
    if len(prepared.auth) != len(signed.auth):
        raise EnvelopeMismatch("The signed authorizations do not match the prepared transaction.")
    for before, after in zip(prepared.auth, signed.auth, strict=True):
        before_credentials = _get_address_credentials(before.credentials)
        after_credentials = _get_address_credentials(after.credentials)
        if before_credentials is None or after_credentials is None:
            # Source-account credentials would authorize with the sponsor's own authority: never relayed.
            raise EnvelopeMismatch("The transaction asks for an authorization that cannot be relayed.")
        address = Address.from_xdr_sc_address(after_credentials.address).address
        if address != wallet or Address.from_xdr_sc_address(before_credentials.address).address != wallet:
            raise EnvelopeMismatch("Only the wallet's own authorizations can be relayed.")
        if before_credentials.nonce.int64 != after_credentials.nonce.int64:
            raise EnvelopeMismatch("The signed authorizations do not match the prepared transaction.")
        if before.root_invocation.to_xdr() != after.root_invocation.to_xdr():
            raise EnvelopeMismatch("The signed authorizations do not match the prepared transaction.")
        if after_credentials.signature.type == stellar_xdr.SCValType.SCV_VOID:
            raise EnvelopeMismatch("The transaction has not been signed by the wallet.")
    return list(signed.auth)


async def _relay(session: AsyncSession, tx: BlockchainTransaction, signed: str) -> Submission:
    """A smart wallet returns the prepared transaction with its authorization entries signed. Only those
    signatures are taken from it: the call is the prepared one and the envelope is rebuilt, re-simulated (running
    the wallet's ``__check_auth``) and signed by the sponsor. The relayed hash replaces the prepared one."""
    network = get_network()
    sponsor = sponsor_keypair()
    previous = (tx.verification_metadata or {}).get("relay")
    if previous and previous.get("envelope_xdr"):
        # A retry after a lost response: send the same envelope again (the network answers DUPLICATE or has it).
        return Submission(xdr=str(previous["envelope_xdr"]))
    if sponsor is None:
        raise ValidationFailed(
            "Smart-wallet transactions need the platform fee sponsor, which is not configured.",
            code="sponsorship_unavailable",
        )
    try:
        envelope = TransactionEnvelope.from_xdr(signed, network.passphrase)
        prepared = TransactionEnvelope.from_xdr(tx.unsigned_xdr or "", network.passphrase)
    except Exception as exc:
        raise EnvelopeMismatch("The signed transaction could not be decoded.") from exc
    auth = _check_signed_authorization(
        _single_invocation(prepared), _single_invocation(envelope), tx.source_address or ""
    )
    # Policy preview, then the read transaction ends: the simulation below is network I/O, and no database lock
    # (row or advisory) may be held across it. The binding check runs again once the real fee is known.
    decision = await evaluate(session, tx)
    if not decision.sponsored:
        raise ValidationFailed(refusal_message(decision.reason), code="sponsorship_refused")
    await session.commit()
    try:
        relayed = await get_adapter().relay(
            _single_invocation(envelope).host_function, auth, sponsor, get_settings().sponsor_max_fee_stroops
        )
    except ContractError as exc:
        raw = (exc.raw or "").lower()
        if "auth" in raw or (exc.code is not None and 100 <= exc.code < 200):
            raise ValidationFailed(
                "The smart wallet did not accept the signature. Sign again with its passkey.",
                code="signature_invalid",
                details={"contract_error": exc.name},
            ) from exc
        raise ValidationFailed(
            exc.message, code="contract_rejected", details={"contract_error": exc.name}
        ) from exc
    except ChainUnavailable as exc:
        raise BlockchainError(str(exc)) from exc
    prepared_hash = tx.transaction_hash
    already = await existing_record(session, relayed.tx_hash)
    if already is not None:
        return Submission(xdr=relayed.signed_xdr, sponsorship=already)
    tx.transaction_hash = relayed.tx_hash
    tx.fee_stroops = relayed.fee_stroops
    # One transaction for the whole record: the daily caps are re-checked against the real fee under the user's
    # advisory lock, and the transaction row, its relay memo and the sponsorship row commit together.
    decision = await check_budget(session, tx.user_id, relayed.fee_stroops, lock=True)
    if not decision.sponsored:
        await session.rollback()
        raise ValidationFailed(refusal_message(decision.reason), code="sponsorship_refused")
    row = _record(
        session,
        tx,
        kind=SponsorshipKind.RELAY,
        purpose=str((tx.verification_metadata or {}).get("action") or tx.transaction_type.value),
        user_id=tx.user_id,
        source=tx.source_address,
        envelope_hash=relayed.tx_hash,
        inner_hash=None,
        max_fee=relayed.fee_stroops,
        contract_id=tx.contract_id,
        function_name=tx.function_name,
        details={"prepared_hash": prepared_hash},
    )
    tx.verification_metadata = {
        **tx.verification_metadata,
        "relay": {"prepared_hash": prepared_hash, "envelope_xdr": relayed.signed_xdr},
    }
    # Durable before sending: a lost response must never leave the network holding a transaction whose hash the
    # database does not know.
    await session.commit()
    return Submission(xdr=relayed.signed_xdr, sponsorship=row)


async def settle(session: AsyncSession, tx: BlockchainTransaction, outcome: TxOutcome | None = None) -> None:
    """Mirrors a sponsored transaction's final state (and the fee the sponsor was actually charged)."""
    meta = (tx.verification_metadata or {}).get("sponsorship")
    if not meta:
        return
    row = await session.get(SponsoredTransaction, uuid.UUID(str(meta["id"])))
    if row is None or row.status != SponsorshipStatus.SUBMITTED:
        return
    await apply_outcome(row, outcome, failure=tx.failure_reason)


async def apply_outcome(
    row: SponsoredTransaction, outcome: TxOutcome | None, failure: str | None = None
) -> None:
    if outcome is not None and outcome.status == "SUCCESS":
        row.status = SponsorshipStatus.CONFIRMED
        row.confirmed_at = outcome.ledger_close_time or utcnow()
    elif outcome is None or outcome.status in ("FAILED", "NOT_FOUND"):
        row.status = SponsorshipStatus.FAILED
        row.failure_reason = (outcome.failure_reason if outcome else None) or failure
    else:
        return
    if outcome is not None and outcome.status != "NOT_FOUND":
        row.ledger_sequence = outcome.ledger
        if outcome.fee_charged is not None:
            row.fee_charged_stroops = outcome.fee_charged
    else:
        row.fee_charged_stroops = 0  # never included: nothing was charged


# --- Generic entry point for other transaction kinds -------------------------------------------------------


async def sponsor_envelope(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    signed_xdr: str,
    purpose: str,
    blockchain_transaction: BlockchainTransaction | None = None,
) -> Submission:
    """Fee-bumps any user-signed envelope whose operations are all sponsorable (calls to the allowed contracts'
    contributor-side functions, trustlines to allowed assets). Returns the envelope unchanged when it is not.

    For flows outside the escrow chain actions (trustlines, claims): the caller has already verified who signed
    the envelope and submits ``Submission.xdr``; the recorded row is finalised with ``apply_outcome``."""
    if not is_enabled():
        return Submission(xdr=signed_xdr)
    network = get_network()
    try:
        envelope = TransactionEnvelope.from_xdr(signed_xdr, network.passphrase)
    except Exception:
        return Submission(xdr=signed_xdr)
    contract_id: str | None = None
    function_name: str | None = None
    allowed_functions = set(get_settings().sponsor_allowed_functions)
    for op in envelope.transaction.operations:
        if isinstance(op, ChangeTrust):
            asset = op.asset
            code = getattr(asset, "code", None)
            issuer = getattr(asset, "issuer", None)
            if (code, issuer) not in _allowed_assets():
                return Submission(xdr=signed_xdr)
            function_name = function_name or "change_trust"
            continue
        if isinstance(op, InvokeHostFunction) and op.host_function.invoke_contract is not None:
            call = op.host_function.invoke_contract
            target = Address.from_xdr_sc_address(call.contract_address).address
            name = call.function_name.sc_symbol.decode()
            if target not in allowed_contracts() or name not in allowed_functions:
                return Submission(xdr=signed_xdr)
            contract_id, function_name = target, name
            continue
        return Submission(xdr=signed_xdr)
    resource_fee = (
        int(envelope.transaction.soroban_data.resource_fee.int64) if envelope.transaction.soroban_data else 0
    )
    decision = await check_budget(
        session, user_id, envelope.transaction.fee - resource_fee + network.base_fee + resource_fee, lock=True
    )
    if not decision.sponsored:
        logger.info("sponsorship_refused", purpose=purpose, reason=decision.reason)
        return Submission(xdr=signed_xdr)
    xdr, bump_hash, max_fee = fee_bump(signed_xdr)
    row = _record(
        session,
        blockchain_transaction,
        kind=SponsorshipKind.FEE_BUMP,
        purpose=purpose,
        user_id=user_id,
        source=envelope.transaction.source.account_id,
        envelope_hash=bump_hash,
        inner_hash=envelope.hash_hex(),
        max_fee=max_fee,
        contract_id=contract_id,
        function_name=function_name,
    )
    return Submission(xdr=xdr, sponsorship=row)


# --- Staff view ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SponsorStatus:
    enabled: bool
    address: str | None
    balance_xlm: Decimal | None
    low_balance: bool
    stopped: bool  # below the stop threshold: nothing is sponsored until it is topped up


async def sponsor_status() -> SponsorStatus:
    settings = get_settings()
    sponsor = sponsor_keypair()
    if sponsor is None:
        return SponsorStatus(False, None, None, False, False)
    balance = await sponsor_balance(fresh=True)
    balance_xlm = from_stroops(balance) if balance is not None else None
    low = balance is not None and balance < settings.sponsor_low_balance_xlm * STROOPS_PER_XLM
    stopped = balance is not None and balance < settings.sponsor_min_balance_xlm * STROOPS_PER_XLM
    return SponsorStatus(True, sponsor.public_key, balance_xlm, low, stopped)


def is_fee_bump(xdr: str) -> bool:
    return FeeBumpTransactionEnvelope.is_fee_bump_transaction_envelope(xdr)


__all__ = [
    "Decision",
    "SponsorStatus",
    "Submission",
    "apply_outcome",
    "check_budget",
    "day_start",
    "envelope_hashes",
    "evaluate",
    "existing_record",
    "fee_bump",
    "is_enabled",
    "is_fee_bump",
    "prepare_submission",
    "refusal_message",
    "settle",
    "sponsor_balance",
    "sponsor_envelope",
    "sponsor_keypair",
    "sponsor_status",
    "usage_today",
]
