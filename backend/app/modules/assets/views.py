"""Read models for trustline guidance: a user's wallets and the assets they can receive, the trustline state of a
bounty's applicants (for the requester), and whether a wallet can fund a bounty's escrow.

Database discipline: the rows a view needs are read first, one query per collection and never one per row, and the
read transaction is closed before the Horizon calls, which then run together."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.assets import NATIVE, is_contract_address
from app.blockchain.config import get_network
from app.blockchain.horizon import AccountState, HorizonUnavailable, get_horizon
from app.core.exceptions import Forbidden, NotFound
from app.core.money import ZERO
from app.core.rbac import Permission, has_permission
from app.core.schemas import asset_from_identifier
from app.modules.applications.models import ApplicationStatus, BountyApplication
from app.modules.assets import checks
from app.modules.assets import service as registry
from app.modules.assets.models import AssetKind, ContractStatus
from app.modules.assets.schemas import (
    ApplicantTrustline,
    BountyTrustlines,
    FundingReadiness,
    TrustlineState,
    TrustlineStatus,
    WalletAssets,
)
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.payments.models import EscrowState
from app.modules.users import repository as users_repo
from app.modules.users.models import User

# Horizon reads per request run concurrently, but never more than this many at once.
_CONCURRENCY = 8


async def wallet_assets(session: AsyncSession, user: User) -> list[WalletAssets]:
    """Each verified wallet on this network, its XLM, and whether it can receive every enabled reward asset."""
    network = get_network()
    wallets = [w for w in await users_repo.verified_wallets(session, user.id) if w.network == network.network]
    assets = [
        r
        for r in await registry.load_registry(session)
        if r.is_enabled and r.contract_status == ContractStatus.DEPLOYED and r.kind == AssetKind.CLASSIC
    ]
    rows = [(w.id, w.public_address, w.network) for w in wallets]
    await session.rollback()  # the Horizon reads below run together, with no transaction open

    async def load(address: str) -> tuple[AccountState | None, bool | None]:
        if is_contract_address(address):
            return None, True  # a smart wallet holds SAC balances in contract storage, not in trustlines
        try:
            account = await get_horizon().load_account(address)
        except HorizonUnavailable:
            return None, None
        return account, account is not None

    loaded = dict(
        zip(
            [address for _id, address, _net in rows],
            await asyncio.gather(*(load(address) for _id, address, _net in rows)),
            strict=True,
        )
    )
    out: list[WalletAssets] = []
    for wallet_id, address, wallet_network in rows:
        native_balance = native_spendable = None
        account, account_exists = loaded[address]
        if account is not None:
            native = account.balance(NATIVE)
            native_balance = native.balance if native else ZERO
            native_spendable = account.native_spendable
        lines: list[TrustlineStatus] = []
        for asset in assets:
            if is_contract_address(address):
                state, balance = TrustlineState.NOT_REQUIRED, None
            elif account_exists is None:
                state, balance = TrustlineState.UNKNOWN, None
            else:
                state, balance = checks.state_from_account(account, asset.identifier)
            lines.append(
                TrustlineStatus(
                    asset=asset_from_identifier(asset.identifier),
                    address=address,
                    state=state,
                    balance=balance,
                )
            )
        out.append(
            WalletAssets(
                wallet_id=wallet_id,
                address=address,
                network=wallet_network,
                account_exists=account_exists,
                native_balance=native_balance,
                native_spendable=native_spendable,
                trustlines=lines,
            )
        )
    return out


async def bounty_trustlines(session: AsyncSession, user: User, bounty_id: uuid.UUID) -> BountyTrustlines:
    """For the requester: can each live applicant's payout wallet receive the bounty's asset?"""
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None:
        raise NotFound("Bounty not found.")
    if bounty.requester_id != user.id and not has_permission(user, Permission.APPLICATION_VIEW_ALL):
        raise Forbidden("Only the requester can see applicants' wallets.")
    identifier = bounty.reward_asset_identifier or NATIVE
    contributor_ids = list(
        dict.fromkeys(
            (
                await session.scalars(
                    select(BountyApplication.contributor_id)
                    .where(
                        BountyApplication.bounty_id == bounty.id,
                        BountyApplication.status.in_([ApplicationStatus.PENDING, ApplicationStatus.ACCEPTED]),
                    )
                    .order_by(BountyApplication.created_at.desc())
                    .limit(100)
                )
            ).all()
        )
    )
    network = get_network().network
    # One query for every applicant's payout wallet, then one Horizon read per distinct address.
    wallets = await users_repo.primary_wallets(session, contributor_ids, network)
    asset = await registry.by_identifier(session, identifier)
    requires_trustline = bool(asset and asset.kind == AssetKind.CLASSIC)
    await session.rollback()  # nothing is read from the database while Horizon is being asked
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def check(contributor_id: uuid.UUID) -> ApplicantTrustline:
        wallet = wallets.get(contributor_id)
        if wallet is None:
            return ApplicantTrustline(
                contributor_id=contributor_id, address=None, state=TrustlineState.NO_WALLET
            )
        async with semaphore:
            state, _ = await checks.trustline_state(identifier, wallet.public_address)
        return ApplicantTrustline(contributor_id=contributor_id, address=wallet.public_address, state=state)

    results = list(await asyncio.gather(*(check(cid) for cid in contributor_ids)))
    return BountyTrustlines(
        asset=asset_from_identifier(identifier),
        requires_trustline=requires_trustline,
        applicants=results,
    )


async def funding_readiness(
    session: AsyncSession, user: User, bounty_id: uuid.UUID, wallet_address: str
) -> FundingReadiness:
    """Can this wallet fund the bounty's next deposit? Guidance for the escrow panel before anything is signed."""
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None or not bounty_service.can_view(bounty, user):
        raise NotFound("Bounty not found.")
    if bounty.requester_id != user.id:
        raise Forbidden("Only the bounty's requester can fund it.")
    escrow = await bounty_repo.get_escrow(session, bounty.id)
    identifier = (escrow.asset_identifier if escrow else None) or bounty.reward_asset_identifier or NATIVE
    required = bounty.total_reward
    if escrow is not None and escrow.state == EscrowState.AWAITING_FUNDING:
        required = max(ZERO, escrow.required_amount - escrow.funded_amount)
    state, available = await checks.spendable_balance(identifier, wallet_address)
    problem = checks.funding_problem(identifier, state, available, required)
    return FundingReadiness(
        asset=asset_from_identifier(identifier),
        address=wallet_address,
        required=required,
        available=available if available is not None else None,
        trustline=state,
        ready=problem is None and state != TrustlineState.UNKNOWN,
        message=problem[1] if problem else None,
        faucet_url=registry.faucet_url(identifier),
    )
