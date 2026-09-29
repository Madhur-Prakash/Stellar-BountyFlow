"""Wallet options, passkey smart wallets, the payout wallet choice and the fee sponsorship overview."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain import passkey, sponsorship
from app.blockchain.config import get_network
from app.blockchain.soroban import ContractError
from app.blockchain.transactions import ChainRejected, ChainUnavailable, get_adapter
from app.cache.invalidation import invalidate_profile
from app.core.config import get_settings
from app.core.exceptions import BlockchainError, Conflict, NotFound, ServiceUnavailable, ValidationFailed
from app.core.logging import get_logger
from app.core.money import from_stroops
from app.core.schemas import UserSummary
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.compliance import screening
from app.modules.users import repository as users_repo
from app.modules.users.models import User, Wallet, WalletVerificationStatus
from app.modules.users.schemas import WalletOut
from app.modules.wallets.models import (
    PasskeyWallet,
    PasskeyWalletStatus,
    SponsoredTransaction,
    SponsorshipKind,
    SponsorshipStatus,
)
from app.modules.wallets.schemas import (
    PasskeyOptions,
    PasskeyWalletCreate,
    PasskeyWalletOut,
    SponsoredTransactionOut,
    SponsorshipOptions,
    SponsorshipOverview,
    WalletCandidateOut,
    WalletOptions,
)

logger = get_logger(__name__)

# A user may keep a few passkey wallets (for example one per device without synced passkeys), not unlimited:
# each deployment is paid by the platform.
MAX_PASSKEY_WALLETS = 3
DEPLOY_GRACE = timedelta(seconds=90)


class _Unset:
    """Sentinel: "no sponsorship row was passed", which None cannot express (None means "there is none")."""


_UNSET = _Unset()


def _passkey_unavailable_reason() -> str | None:
    if not sponsorship.is_enabled():
        return "Passkey wallets need the platform fee sponsor, which is not configured on this server."
    if not get_settings().web_auth_contract_id:
        return "Passkey wallets need the web authentication contract, which is not configured on this server."
    return None


async def options(session: AsyncSession, user: User) -> WalletOptions:
    settings = get_settings()
    network = get_network()
    sponsor = sponsorship.sponsor_keypair()
    used, _ = await sponsorship.usage_today(session, user.id) if sponsor else (0, 0)
    reason = _passkey_unavailable_reason()
    return WalletOptions(
        sponsorship=SponsorshipOptions(
            enabled=sponsor is not None,
            sponsor_address=sponsor.public_key if sponsor else None,
            functions=list(settings.sponsor_allowed_functions) if sponsor else [],
            daily_tx_limit=settings.sponsor_daily_tx_limit,
            used_today=used,
        ),
        passkey=PasskeyOptions(
            enabled=reason is None,
            unavailable_reason=reason,
            wasm_hash=settings.passkey_wallet_wasm_hash,
            rpc_url=network.soroban_rpc_url,
            network_passphrase=network.passphrase,
        ),
    )


# --- Passkey wallets ----------------------------------------------------------------------------------------


async def _linked_addresses(session: AsyncSession, user_id: uuid.UUID) -> set[str]:
    return {w.public_address for w in await users_repo.verified_wallets(session, user_id)}


def _serialize(row: PasskeyWallet, linked: set[str]) -> PasskeyWalletOut:
    network = get_network()
    return PasskeyWalletOut(
        id=row.id,
        contract_id=row.contract_id,
        key_id=row.key_id,
        public_key=row.public_key,
        network=row.network,
        status=row.status,
        wasm_hash=row.wasm_hash,
        deploy_tx_hash=row.deploy_tx_hash,
        creation_ledger=row.creation_ledger,
        deployed_at=row.deployed_at,
        failure_reason=row.failure_reason,
        explorer_url=network.tx_url(row.deploy_tx_hash) if row.status != PasskeyWalletStatus.FAILED else None,
        linked=row.contract_id in linked,
        created_at=row.created_at,
    )


async def _sponsored_row(session: AsyncSession, wallet: PasskeyWallet) -> SponsoredTransaction | None:
    return await session.scalar(
        select(SponsoredTransaction).where(
            SponsoredTransaction.passkey_wallet_id == wallet.id,
            SponsoredTransaction.envelope_hash == wallet.deploy_tx_hash,
        )
    )


async def _sponsored_rows(
    session: AsyncSession, wallets: list[PasskeyWallet]
) -> dict[uuid.UUID, SponsoredTransaction]:
    """The deployments' sponsorship rows in one query (never one per wallet in a loop)."""
    if not wallets:
        return {}
    rows = (
        await session.scalars(
            select(SponsoredTransaction).where(
                SponsoredTransaction.passkey_wallet_id.in_([w.id for w in wallets])
            )
        )
    ).all()
    by_wallet = {w.id: w.deploy_tx_hash for w in wallets}
    return {
        r.passkey_wallet_id: r
        for r in rows
        if r.passkey_wallet_id and r.envelope_hash == by_wallet.get(r.passkey_wallet_id)
    }


async def refresh_deployment(
    session: AsyncSession, wallet: PasskeyWallet, sponsored: SponsoredTransaction | _Unset | None = _UNSET
) -> bool:
    """Moves a DEPLOYING wallet to ACTIVE once the network confirms the deployment *and* the contract reads back
    with the expected code, or to FAILED. Returns whether anything changed.

    The caller may pass the deployment's already-loaded sponsorship row (see :func:`_sponsored_rows`)."""
    if wallet.status != PasskeyWalletStatus.DEPLOYING or not wallet.deploy_tx_hash:
        return False
    adapter = get_adapter()
    try:
        outcome = await adapter.get_outcome(wallet.deploy_tx_hash)
    except ChainUnavailable:
        return False
    row = await _sponsored_row(session, wallet) if isinstance(sponsored, _Unset) else sponsored
    if outcome.status == "SUCCESS":
        try:
            wasm = await adapter.contract_wasm_hash(wallet.contract_id)
        except ChainUnavailable:
            return False
        if wasm != wallet.wasm_hash:
            logger.error("passkey_wallet_code_mismatch", contract_id=wallet.contract_id, wasm=wasm)
            wallet.status = PasskeyWalletStatus.FAILED
            wallet.failure_reason = "The deployed contract does not run the expected wallet code."
        else:
            wallet.status = PasskeyWalletStatus.ACTIVE
            wallet.creation_ledger = outcome.ledger
            wallet.deployed_at = outcome.ledger_close_time or utcnow()
            add_event(
                session,
                event_type=EventType.WALLET_PASSKEY_CREATED,
                aggregate_type="user",
                aggregate_id=wallet.user_id,
                actor_id=wallet.user_id,
                payload={"user_id": wallet.user_id, "contract_id": wallet.contract_id},
            )
    elif outcome.status == "FAILED":
        wallet.status = PasskeyWalletStatus.FAILED
        wallet.failure_reason = outcome.failure_reason or "The wallet deployment failed on the network."
    elif outcome.status == "NOT_FOUND":
        deadline = wallet.created_at + timedelta(seconds=get_network().tx_timeout_seconds) + DEPLOY_GRACE
        if utcnow() <= deadline:
            return False
        wallet.status = PasskeyWalletStatus.FAILED
        wallet.failure_reason = "The network never included the wallet deployment."
    else:
        return False
    if row is not None and row.status == SponsorshipStatus.SUBMITTED:
        await sponsorship.apply_outcome(row, outcome, failure=wallet.failure_reason)
    return True


async def list_passkey_wallets(session: AsyncSession, user: User) -> list[PasskeyWalletOut]:
    rows = list(
        (
            await session.scalars(
                select(PasskeyWallet)
                .where(PasskeyWallet.user_id == user.id, PasskeyWallet.network == get_network().network)
                .order_by(PasskeyWallet.created_at.desc())
            )
        ).all()
    )
    deploying = [r for r in rows if r.status == PasskeyWalletStatus.DEPLOYING and r.deploy_tx_hash]
    sponsored = await _sponsored_rows(session, deploying)
    changed = False
    for row in deploying:
        changed = await refresh_deployment(session, row, sponsored.get(row.id)) or changed
    if changed:
        await session.commit()  # every wallet's new state and its sponsorship row in one transaction
    linked = await _linked_addresses(session, user.id)
    return [_serialize(r, linked) for r in rows]


async def create_passkey_wallet(
    session: AsyncSession, user: User, data: PasskeyWalletCreate
) -> PasskeyWalletOut:
    """Relays a passkey-kit wallet deployment through the sponsor (the user needs no XLM)."""
    reason = _passkey_unavailable_reason()
    if reason:
        raise ServiceUnavailable(reason, code="passkey_unavailable")
    sponsor = sponsorship.sponsor_keypair()
    assert sponsor is not None
    network = get_network()
    deployment = passkey.check_deployment(data.deploy_xdr, data.key_id, data.public_key)
    # The platform pays for this deployment, and the wallet will hold funds, so screen the address first.
    await screening.enforce(
        user_id=user.id, addresses=[deployment.contract_id], context=screening.PASSKEY_DEPLOYMENT
    )

    existing = await session.scalar(
        select(PasskeyWallet).where(
            PasskeyWallet.network == network.network, PasskeyWallet.contract_id == deployment.contract_id
        )
    )
    if existing is not None:
        if existing.user_id != user.id:
            raise Conflict("This passkey wallet belongs to another BountyFlow account.")
        if existing.status != PasskeyWalletStatus.FAILED:
            return _serialize(existing, await _linked_addresses(session, user.id))
    active = await session.scalar(
        select(func.count(PasskeyWallet.id)).where(
            PasskeyWallet.user_id == user.id,
            PasskeyWallet.network == network.network,
            PasskeyWallet.status != PasskeyWalletStatus.FAILED,
        )
    )
    if (active or 0) >= MAX_PASSKEY_WALLETS:
        raise Conflict(f"You can create up to {MAX_PASSKEY_WALLETS} passkey wallets.")

    # Policy preview, then the read transaction ends: simulating the deployment is network I/O, and no database
    # lock may be held across it. The binding check runs again below, once the real fee is known.
    decision = await sponsorship.check_budget(session, user.id, 0, lock=False)
    if not decision.sponsored:
        raise ValidationFailed(sponsorship.refusal_message(decision.reason), code="sponsorship_refused")
    await session.commit()
    adapter = get_adapter()
    try:
        relayed = await adapter.relay(
            deployment.host_function, deployment.auth, sponsor, get_settings().sponsor_max_fee_stroops
        )
    except ContractError as exc:
        raise ValidationFailed(
            f"The wallet deployment was rejected during simulation: {exc.message}", code="contract_rejected"
        ) from exc
    except ChainUnavailable as exc:
        raise BlockchainError(str(exc)) from exc
    # One transaction from here to the commit below: the caps under the user's advisory lock, the wallet row,
    # its sponsorship row and the audit entry all land together, or none of them do.
    decision = await sponsorship.check_budget(session, user.id, relayed.fee_stroops, lock=True)
    if not decision.sponsored:
        await session.rollback()
        raise ValidationFailed(sponsorship.refusal_message(decision.reason), code="sponsorship_refused")

    if existing is not None:  # a failed earlier attempt for the same passkey: try again on the same row
        wallet = existing
        wallet.status = PasskeyWalletStatus.DEPLOYING
        wallet.failure_reason = None
        wallet.created_at = utcnow()
    else:
        wallet = PasskeyWallet(
            id=uuid.uuid4(),
            user_id=user.id,
            network=network.network,
            contract_id=deployment.contract_id,
            key_id=deployment.key_id,
            public_key=deployment.public_key,
            wasm_hash=deployment.wasm_hash,
            status=PasskeyWalletStatus.DEPLOYING,
            created_at=utcnow(),
        )
        session.add(wallet)
    wallet.deploy_tx_hash = relayed.tx_hash
    await session.flush()
    # `(network, envelope_hash)` is unique: a retry of the same deployment reuses the row it already wrote.
    if await sponsorship.existing_record(session, relayed.tx_hash) is None:
        session.add(
            SponsoredTransaction(
                id=uuid.uuid4(),
                user_id=user.id,
                passkey_wallet_id=wallet.id,
                kind=SponsorshipKind.RELAY,
                purpose="WALLET_DEPLOY",
                network=network.network,
                sponsor_address=sponsor.public_key,
                source_address=deployment.contract_id,
                envelope_hash=relayed.tx_hash,
                max_fee_stroops=relayed.fee_stroops,
                status=SponsorshipStatus.SUBMITTED,
                details={"wasm_hash": deployment.wasm_hash},
            )
        )
    audit.record(
        session,
        actor_id=user.id,
        action="wallet.passkey_deploy_submitted",
        entity_type="wallet",
        entity_id=wallet.id,
        metadata={"contract_id": deployment.contract_id, "hash": relayed.tx_hash},
        is_public=False,
    )
    # Durable before sending, so a lost response never hides a deployment the network has.
    try:
        await session.commit()
    except IntegrityError as exc:
        # A concurrent create of the same passkey wallet won the unique (network, contract_id) index.
        await session.rollback()
        raise Conflict("This passkey wallet is already being created.") from exc
    try:
        await adapter.submit(relayed.signed_xdr, relayed.tx_hash)
    except ChainRejected as exc:
        wallet.status = PasskeyWalletStatus.FAILED
        wallet.failure_reason = str(exc)
        row = await _sponsored_row(session, wallet)
        if row is not None:
            await sponsorship.apply_outcome(row, None, failure=str(exc))
        await session.commit()
        raise ValidationFailed(
            f"The network rejected the wallet deployment: {exc}", code="deploy_rejected"
        ) from exc
    except ChainUnavailable:
        logger.warning("passkey_deploy_response_lost", contract_id=wallet.contract_id)
    if await refresh_deployment(session, wallet):
        await session.commit()
    return _serialize(wallet, await _linked_addresses(session, user.id))


async def wallet_candidates(session: AsyncSession, user: User, key_id: str) -> WalletCandidateOut:
    """Birth claims of the user's own passkey wallet for ``key_id``, in passkey-kit's lookup format, so the wallet
    can be connected on a device that has the (synced) passkey but no local record. passkey-kit still verifies
    every claim on-chain and asks for a fresh assertion."""
    network = get_network()
    try:
        latest = await get_adapter().latest_ledger()
    except ChainUnavailable as exc:
        raise BlockchainError(str(exc)) from exc
    row = await session.scalar(
        select(PasskeyWallet).where(
            PasskeyWallet.user_id == user.id,
            PasskeyWallet.network == network.network,
            PasskeyWallet.key_id == key_id,
            PasskeyWallet.status == PasskeyWalletStatus.ACTIVE,
        )
    )
    candidates: list[dict[str, object]] = []
    if row is not None and row.deploy_tx_hash and row.creation_ledger:
        candidates.append(
            {
                "contractId": row.contract_id,
                "birthWasmHash": row.wasm_hash,
                "creationTransactionHash": row.deploy_tx_hash,
                "creationLedger": row.creation_ledger,
            }
        )
    # Addresses derive from the credential id alone, so BountyFlow's record is the complete answer for it.
    return WalletCandidateOut(complete=True, indexed_through_ledger=latest, candidates=candidates)


# --- Payout wallet -------------------------------------------------------------------------------------------


async def set_primary_wallet(session: AsyncSession, user: User, wallet_id: uuid.UUID) -> WalletOut:
    """Chooses the payout wallet. Every write — the demotions, the promotion and the audit entry — commits once.

    The user's wallet rows are locked in a fixed order (by id) so two concurrent choices serialise instead of
    leaving two primary wallets behind."""
    await session.execute(
        select(Wallet.id)
        .where(Wallet.user_id == user.id, Wallet.verification_status == WalletVerificationStatus.VERIFIED)
        .order_by(Wallet.id)
        .with_for_update()
    )
    wallet = await session.get(Wallet, wallet_id)
    if (
        wallet is None
        or wallet.user_id != user.id
        or wallet.verification_status != WalletVerificationStatus.VERIFIED
    ):
        raise NotFound("Wallet not found.")
    await session.execute(
        update(Wallet)
        .where(Wallet.user_id == user.id, Wallet.network == wallet.network, Wallet.id != wallet.id)
        .values(is_primary=False)
    )
    wallet.is_primary = True
    audit.record(
        session,
        actor_id=user.id,
        action="wallet.primary_set",
        entity_type="wallet",
        entity_id=wallet.id,
        metadata={"address": wallet.public_address},
        is_public=False,
    )
    await session.commit()
    await session.refresh(wallet)
    await invalidate_profile(user.username)
    return WalletOut.model_validate(wallet)


# --- Staff overview --------------------------------------------------------------------------------------------


async def sponsorship_overview(session: AsyncSession, limit: int = 12) -> SponsorshipOverview:
    settings = get_settings()
    network = get_network()
    status = await sponsorship.sponsor_status()
    day = sponsorship.day_start()
    today = (
        await session.execute(
            select(
                func.count(SponsoredTransaction.id),
                func.coalesce(func.sum(SponsoredTransaction.fee_charged_stroops), 0),
            ).where(SponsoredTransaction.created_at >= day, SponsoredTransaction.network == network.network)
        )
    ).one()
    rows = (
        await session.execute(
            select(SponsoredTransaction, User)
            .outerjoin(User, User.id == SponsoredTransaction.user_id)
            .where(SponsoredTransaction.network == network.network)
            .order_by(SponsoredTransaction.created_at.desc())
            .limit(limit)
        )
    ).all()
    recent = [
        SponsoredTransactionOut(
            id=row.id,
            kind=row.kind,
            purpose=row.purpose,
            status=row.status,
            user=UserSummary(
                id=user.id, username=user.username, display_name=user.display_name, avatar_url=user.avatar_url
            )
            if user
            else None,
            source_address=row.source_address,
            envelope_hash=row.envelope_hash,
            inner_hash=row.inner_hash,
            contract_id=row.contract_id,
            function_name=row.function_name,
            max_fee=from_stroops(row.max_fee_stroops),
            fee_charged=from_stroops(row.fee_charged_stroops)
            if row.fee_charged_stroops is not None
            else None,
            ledger_sequence=row.ledger_sequence,
            failure_reason=row.failure_reason,
            explorer_url=network.tx_url(row.envelope_hash),
            created_at=row.created_at,
            confirmed_at=row.confirmed_at,
        )
        for row, user in rows
    ]
    stroops = sponsorship.STROOPS_PER_XLM
    return SponsorshipOverview(
        enabled=status.enabled,
        sponsor_address=status.address,
        balance=status.balance_xlm,
        low_balance=status.low_balance,
        stopped=status.stopped,
        low_balance_threshold=from_stroops(settings.sponsor_low_balance_xlm * stroops),
        stop_threshold=from_stroops(settings.sponsor_min_balance_xlm * stroops),
        max_fee=from_stroops(settings.sponsor_max_fee_stroops),
        daily_tx_limit=settings.sponsor_daily_tx_limit,
        daily_fee_limit=from_stroops(settings.sponsor_daily_fee_limit_stroops),
        sponsored_today=int(today[0] or 0),
        fees_today=from_stroops(int(today[1] or 0)),
        recent=recent,
    )
