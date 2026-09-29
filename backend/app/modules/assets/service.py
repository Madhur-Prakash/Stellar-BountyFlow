"""Reward asset registry: which assets bounties may pay in, per network.

XLM and Circle's USDC are enabled by default. Admins add other classic assets by code and issuer, or by the
contract id of their Stellar Asset Contract (SAC). The backend never trusts a client-supplied contract id: it derives
the SAC address from the asset, checks on Soroban that the contract exists and reports 7 decimals, and reads the
issuer's authorization flags from Horizon. An asset whose SAC is missing stays disabled until an admin deploys it
(``operations.prepare_deploy``). Entries are never deleted, only disabled.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk.strkey import StrKey

from app.blockchain.assets import NATIVE, SAC_DECIMALS, InvalidAsset, make_ref, parse_identifier
from app.blockchain.config import get_network
from app.blockchain.horizon import HorizonUnavailable, get_horizon
from app.blockchain.soroban import ContractError
from app.blockchain.tokens import TokenMetadata, get_tokens
from app.blockchain.transactions import ChainUnavailable
from app.cache import keys
from app.cache.redis import cache_delete, cache_get_json, cache_set_json
from app.core.exceptions import (
    BlockchainError,
    Conflict,
    InvalidStateTransition,
    NotFound,
    ValidationFailed,
)
from app.core.logging import get_logger
from app.core.schemas import UserSummary, asset_from_identifier
from app.core.security import utcnow
from app.db.session import session_scope
from app.modules.admin import audit
from app.modules.assets.models import AssetKind, ContractStatus, RewardAsset
from app.modules.assets.schemas import AdminRewardAssetOut, AssetCreate, AssetUpdate, RewardAssetOut
from app.modules.bounties.models import Bounty
from app.modules.users.models import User

logger = get_logger(__name__)

CIRCLE_FAUCET_URL = "https://faucet.circle.com"
TESTNET_USDC = "USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
MAINNET_USDC = "USDC:GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN"
TTL_REGISTRY = 60


@dataclass(frozen=True)
class DefaultAsset:
    identifier: str
    name: str
    symbol: str
    sort_order: int


# Enabled on every fresh database (the 0006 migration inserts the same rows).
DEFAULT_ASSETS: dict[str, tuple[DefaultAsset, ...]] = {
    "testnet": (
        DefaultAsset(NATIVE, "Stellar Lumens", "native", 0),
        DefaultAsset(TESTNET_USDC, "USD Coin", "USDC", 10),
    ),
    "mainnet": (
        DefaultAsset(NATIVE, "Stellar Lumens", "native", 0),
        DefaultAsset(MAINNET_USDC, "USD Coin", "USDC", 10),
    ),
}


def registry_cache_key(network: str) -> str:
    return f"{keys.PREFIX}:assets:{network}"


async def invalidate_registry() -> None:
    await cache_delete(registry_cache_key(get_network().network))


def faucet_url(identifier: str) -> str | None:
    """Where to get test units of an asset: Circle's faucet hands out Testnet USDC."""
    if get_network().network == "testnet" and identifier == TESTNET_USDC:
        return CIRCLE_FAUCET_URL
    return None


# --- Loading ---------------------------------------------------------------------------------------


async def ensure_defaults() -> None:
    """Insert the network's default assets if they are missing (fresh databases and tests). Runs in its own
    transaction, so a caller's open transaction and locks are never committed early."""
    network = get_network()
    defaults = DEFAULT_ASSETS.get(network.network, DEFAULT_ASSETS["testnet"][:1])
    rows = []
    for d in defaults:
        ref = parse_identifier(d.identifier)
        rows.append(
            {
                "id": uuid.uuid4(),
                "network": network.network,
                "identifier": ref.identifier,
                "kind": AssetKind.NATIVE if ref.is_native else AssetKind.CLASSIC,
                "code": ref.code,
                "issuer": ref.issuer,
                "contract_id": network.sac_contract_id(ref.identifier),
                "name": d.name,
                "symbol": d.symbol,
                "decimals": SAC_DECIMALS,
                "contract_status": ContractStatus.DEPLOYED,
                "issuer_flags": {},
                "is_enabled": True,
                "is_default": True,
                "sort_order": d.sort_order,
            }
        )
    async with session_scope() as session:
        await session.execute(pg_insert(RewardAsset).values(rows).on_conflict_do_nothing())


async def load_registry(session: AsyncSession) -> list[RewardAsset]:
    """Every registry entry on the active network (enabled or not), in display order."""
    network = get_network().network
    stmt = (
        select(RewardAsset)
        .where(RewardAsset.network == network)
        .order_by(RewardAsset.sort_order, RewardAsset.code, RewardAsset.identifier)
    )
    rows = list((await session.scalars(stmt)).all())
    if not rows:
        await ensure_defaults()
        rows = list((await session.scalars(stmt)).all())
    return rows


async def get_asset(session: AsyncSession, asset_id: uuid.UUID, *, for_update: bool = False) -> RewardAsset:
    """``for_update`` locks the row for a write, so two admins never decide about the same asset at once."""
    stmt = select(RewardAsset).where(RewardAsset.id == asset_id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(stmt)
    if row is None or row.network != get_network().network:
        raise NotFound("Asset not found.")
    return row


async def by_identifier(session: AsyncSession, identifier: str) -> RewardAsset | None:
    for row in await load_registry(session):
        if row.identifier == identifier:
            return row
    return None


# --- Serialization -------------------------------------------------------------------------------


def serialize(row: RewardAsset) -> RewardAssetOut:
    return RewardAssetOut(
        id=row.id,
        asset=asset_from_identifier(row.identifier),
        name=row.name,
        is_default=row.is_default,
        requires_trustline=row.kind == AssetKind.CLASSIC,
        faucet_url=faucet_url(row.identifier),
    )


def serialize_admin(row: RewardAsset, bounty_count: int, creator: User | None) -> AdminRewardAssetOut:
    return AdminRewardAssetOut(
        **serialize(row).model_dump(),
        is_enabled=row.is_enabled,
        contract_status=row.contract_status,
        symbol=row.symbol,
        decimals=row.decimals,
        issuer_flags={k: bool(v) for k, v in (row.issuer_flags or {}).items()},
        sort_order=row.sort_order,
        bounty_count=bounty_count,
        verified_at=row.verified_at,
        created_by=UserSummary(
            id=creator.id,
            username=creator.username,
            display_name=creator.display_name,
            avatar_url=creator.avatar_url,
        )
        if creator
        else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --- Public reads ------------------------------------------------------------------------------------


async def list_enabled(session: AsyncSession) -> list[RewardAssetOut]:
    """Assets a new bounty can pay in (cached briefly; admin changes invalidate it)."""
    key = registry_cache_key(get_network().network)
    cached = await cache_get_json(key)
    if cached is not None:
        return [RewardAssetOut.model_validate(item) for item in cached]
    items = [
        serialize(r)
        for r in await load_registry(session)
        if r.is_enabled and r.contract_status == ContractStatus.DEPLOYED
    ]
    await cache_set_json(key, [i.model_dump(mode="json") for i in items], TTL_REGISTRY)
    return items


def _not_accepted(code: str) -> ValidationFailed:
    return ValidationFailed(
        f"{code} is not accepted as a reward asset.",
        code="asset_not_supported",
        details=[{"field": "reward_asset", "message": f"{code} is not an enabled reward asset."}],
    )


async def resolve_reward_asset(session: AsyncSession, value: str | None) -> RewardAsset:
    """The enabled registry entry a new (or draft) bounty will pay in. Accepts an identifier ("native" or
    "CODE:ISSUER"), "XLM", or a bare code when exactly one enabled asset uses it."""
    rows = await load_registry(session)
    raw = (value or "").strip()
    if raw in ("", NATIVE, "XLM"):
        identifier = NATIVE
    elif ":" in raw:
        try:
            identifier = parse_identifier(raw).identifier
        except InvalidAsset as exc:
            raise ValidationFailed(
                str(exc), code="asset_not_supported", details=[{"field": "reward_asset", "message": str(exc)}]
            ) from exc
    else:
        matches = [r for r in rows if r.is_enabled and r.code.upper() == raw.upper()]
        if len(matches) > 1:
            raise ValidationFailed(
                f"More than one enabled asset uses the code {raw}. Send its full identifier (CODE:ISSUER).",
                code="asset_ambiguous",
                details=[{"field": "reward_asset", "message": "Ambiguous asset code."}],
            )
        if not matches:
            raise _not_accepted(raw)
        identifier = matches[0].identifier
    row = next((r for r in rows if r.identifier == identifier), None)
    if row is None or not row.is_enabled or row.contract_status != ContractStatus.DEPLOYED:
        raise _not_accepted(row.code if row else raw.partition(":")[0] or raw)
    return row


async def require_fundable(session: AsyncSession, identifier: str) -> RewardAsset:
    """New escrow deposits are only accepted in an enabled asset whose SAC is deployed. Money already in an escrow
    (payouts, refunds, disputes) is never blocked by an asset being disabled later."""
    row = await by_identifier(session, identifier)
    if row is None or not row.is_enabled or row.contract_status != ContractStatus.DEPLOYED:
        code = row.code if row else parse_identifier(identifier).code
        raise ValidationFailed(
            f"{code} is not accepted for new escrow deposits right now.", code="asset_not_supported"
        )
    return row


# --- Admin ---------------------------------------------------------------------------------------------


async def _bounty_counts(session: AsyncSession, identifiers: Sequence[str]) -> dict[str, int]:
    if not identifiers:
        return {}
    rows = await session.execute(
        select(Bounty.reward_asset_identifier, func.count(Bounty.id))
        .where(Bounty.reward_asset_identifier.in_(identifiers), Bounty.network == get_network().network)
        .group_by(Bounty.reward_asset_identifier)
    )
    return {identifier: count for identifier, count in rows.all()}


async def admin_list(session: AsyncSession) -> list[AdminRewardAssetOut]:
    rows = await load_registry(session)
    counts = await _bounty_counts(session, [r.identifier for r in rows])
    creator_ids = {r.created_by_id for r in rows if r.created_by_id}
    creators = (
        {u.id: u for u in (await session.scalars(select(User).where(User.id.in_(creator_ids)))).all()}
        if creator_ids
        else {}
    )
    return [
        serialize_admin(
            r, counts.get(r.identifier, 0), creators.get(r.created_by_id) if r.created_by_id else None
        )
        for r in rows
    ]


async def _admin_out(session: AsyncSession, row: RewardAsset) -> AdminRewardAssetOut:
    await session.refresh(row)  # updated_at is set by the database
    counts = await _bounty_counts(session, [row.identifier])
    creator = await session.get(User, row.created_by_id) if row.created_by_id else None
    return serialize_admin(row, counts.get(row.identifier, 0), creator)


def _chain_error(exc: Exception) -> BlockchainError:
    return BlockchainError(f"The network could not be checked right now: {exc}")


async def _read_metadata(contract_id: str) -> TokenMetadata:
    try:
        return await get_tokens().metadata(contract_id)
    except ContractError as exc:
        raise ValidationFailed(
            "This contract does not answer the token interface (name, symbol, decimals).",
            code="asset_not_token",
            details=[{"field": "contract_id", "message": "Not a token contract."}],
        ) from exc
    except ChainUnavailable as exc:
        raise _chain_error(exc) from exc


def _check_decimals(meta: TokenMetadata) -> None:
    if meta.decimals != SAC_DECIMALS:
        raise ValidationFailed(
            f"The contract reports {meta.decimals} decimals; reward assets use Stellar's 7.",
            code="asset_decimals_unsupported",
        )


async def _issuer_flags(issuer: str) -> dict[str, bool]:
    try:
        account = await get_horizon().load_account(issuer)
    except HorizonUnavailable as exc:
        raise _chain_error(exc) from exc
    if account is None:
        raise ValidationFailed(
            f"The issuer account {issuer} does not exist on {get_network().network}.",
            code="asset_issuer_missing",
            details=[{"field": "issuer", "message": "Issuer account not found."}],
        )
    return {k: v for k, v in account.flags.items() if k.startswith("auth_")}


async def admin_create(session: AsyncSession, user: User, data: AssetCreate) -> AdminRewardAssetOut:
    network = get_network()
    meta: TokenMetadata | None = None
    if data.contract_id:
        contract_id = data.contract_id
        if not StrKey.is_valid_contract(contract_id):
            raise ValidationFailed(
                "Enter a Stellar contract id (C…).",
                details=[{"field": "contract_id", "message": "Must be a C… contract address."}],
            )
        meta = await _read_metadata(contract_id)
        try:
            ref = parse_identifier(meta.name)  # a SAC's name() is "CODE:ISSUER" (or "native")
        except InvalidAsset as exc:
            raise ValidationFailed(
                "Only Stellar Asset Contracts can be reward assets; this token is a custom contract.",
                code="asset_not_sac",
                details=[{"field": "contract_id", "message": "Not a Stellar Asset Contract."}],
            ) from exc
        if ref.is_native or network.sac_contract_id(ref.identifier) != contract_id:
            raise ValidationFailed(
                f"This token calls itself {meta.name} but is not that asset's Stellar Asset Contract.",
                code="asset_not_sac",
                details=[{"field": "contract_id", "message": "Not a Stellar Asset Contract."}],
            )
        deployed = True
    else:
        try:
            ref = make_ref(data.code or "", data.issuer)
        except InvalidAsset as exc:
            field = "issuer" if "issuer" in str(exc).lower() else "code"
            raise ValidationFailed(str(exc), details=[{"field": field, "message": str(exc)}]) from exc
        contract_id = network.sac_contract_id(ref.identifier)
        try:
            deployed = await get_tokens().contract_exists(contract_id)
        except ChainUnavailable as exc:
            raise _chain_error(exc) from exc
        if deployed:
            meta = await _read_metadata(contract_id)
    if await by_identifier(session, ref.identifier) is not None:
        raise Conflict(f"{ref.code} from this issuer is already in the registry.", code="asset_exists")
    if meta is not None:
        _check_decimals(meta)
    assert ref.issuer is not None
    flags = await _issuer_flags(ref.issuer)
    row = RewardAsset(
        id=uuid.uuid4(),
        network=network.network,
        identifier=ref.identifier,
        kind=AssetKind.CLASSIC,
        code=ref.code,
        issuer=ref.issuer,
        contract_id=contract_id,
        name=data.name or ref.code,
        symbol=meta.symbol if meta else ref.code,
        decimals=meta.decimals if meta else SAC_DECIMALS,
        contract_status=ContractStatus.DEPLOYED if deployed else ContractStatus.NOT_DEPLOYED,
        issuer_flags=flags,
        is_enabled=bool(data.enable and deployed),
        is_default=False,
        sort_order=100,
        verified_at=utcnow(),
        created_by_id=user.id,
    )
    session.add(row)
    audit.record(
        session,
        actor_id=user.id,
        action="asset.created",
        entity_type="asset",
        entity_id=row.id,
        metadata={"identifier": row.identifier, "contract_id": contract_id, "deployed": deployed},
        is_public=False,
    )
    await session.commit()
    await invalidate_registry()
    logger.info("reward_asset_created", identifier=row.identifier, deployed=deployed)
    return await _admin_out(session, row)


async def admin_update(
    session: AsyncSession, user: User, asset_id: uuid.UUID, data: AssetUpdate
) -> AdminRewardAssetOut:
    # One transaction: the row is locked, checked and changed, and its audit entry commits with it.
    row = await get_asset(session, asset_id, for_update=True)
    changes: dict[str, Any] = data.model_dump(exclude_unset=True, exclude_none=True)
    if changes.get("is_enabled") is True and row.contract_status != ContractStatus.DEPLOYED:
        raise InvalidStateTransition(
            f"The {row.code} asset contract is not deployed yet. Deploy it before enabling the asset."
        )
    if changes.get("is_enabled") is False and row.is_enabled:
        # Counted in SQL under the same transaction, so a concurrent disable cannot leave the network with none.
        others = await session.scalar(
            select(func.count(RewardAsset.id)).where(
                RewardAsset.network == row.network,
                RewardAsset.is_enabled.is_(True),
                RewardAsset.id != row.id,
            )
        )
        if not others:
            raise InvalidStateTransition("At least one reward asset must stay enabled.")
    for field, value in changes.items():
        setattr(row, field, value)
    if changes:
        audit.record(
            session,
            actor_id=user.id,
            action="asset.updated",
            entity_type="asset",
            entity_id=row.id,
            metadata={"identifier": row.identifier, **changes},
            is_public=False,
        )
    await session.commit()
    await invalidate_registry()
    return await _admin_out(session, row)


@dataclass(frozen=True)
class ChainReads:
    """What the network says about an asset, read before any row is locked."""

    deployed: bool = False
    metadata: TokenMetadata | None = None
    issuer_flags: dict[str, bool] | None = None


async def read_from_chain(row: RewardAsset) -> ChainReads:
    """Reads the asset's SAC and its issuer from the network. Pure I/O: it touches no database row."""
    if row.kind == AssetKind.NATIVE:
        return ChainReads()
    try:
        deployed = await get_tokens().contract_exists(row.contract_id)
    except ChainUnavailable as exc:
        raise _chain_error(exc) from exc
    metadata = None
    if deployed:
        metadata = await _read_metadata(row.contract_id)
        _check_decimals(metadata)
    return ChainReads(
        deployed=deployed,
        metadata=metadata,
        issuer_flags=await _issuer_flags(row.issuer) if row.issuer else None,
    )


def apply_chain_reads(row: RewardAsset, reads: ChainReads) -> None:
    """Writes what the network said onto the locked row. Pure database work, safe to repeat."""
    if reads.metadata is not None:
        row.symbol = reads.metadata.symbol
        row.decimals = reads.metadata.decimals
    if reads.deployed:
        row.contract_status = ContractStatus.DEPLOYED
    if reads.issuer_flags is not None:
        row.issuer_flags = reads.issuer_flags
    row.verified_at = utcnow()


async def admin_verify(session: AsyncSession, user: User, asset_id: uuid.UUID) -> AdminRewardAssetOut:
    # The network is asked first, with nothing locked; the result is then written under the row lock.
    unlocked = await get_asset(session, asset_id)
    reads = await read_from_chain(unlocked)
    await session.rollback()
    row = await get_asset(session, asset_id, for_update=True)
    apply_chain_reads(row, reads)
    audit.record(
        session,
        actor_id=user.id,
        action="asset.verified",
        entity_type="asset",
        entity_id=row.id,
        metadata={"identifier": row.identifier, "contract_status": row.contract_status.value},
        is_public=False,
    )
    await session.commit()
    await invalidate_registry()
    return await _admin_out(session, row)
