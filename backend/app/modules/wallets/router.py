"""Wallet options, passkey smart wallet, payout wallet and fee sponsorship endpoints.

Linking a wallet (challenge / verify / list / unlink) lives with the user's other account data in
``app/modules/users/router.py``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.rate_limit import hit
from app.core.rbac import Permission
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.users.models import User
from app.modules.users.schemas import WalletOut
from app.modules.wallets import service
from app.modules.wallets.schemas import (
    PasskeyWalletCreate,
    PasskeyWalletOut,
    SponsorshipOverview,
    WalletCandidateOut,
    WalletOptions,
)

router = APIRouter(tags=["wallets"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/wallets/options", response_model=WalletOptions)
async def wallet_options(session: SessionDep, user: CurrentUser) -> WalletOptions:
    """What this server offers: fee sponsorship for contributor actions and passkey smart wallets."""
    return await service.options(session, user)


@router.get("/wallets/passkey", response_model=list[PasskeyWalletOut])
async def passkey_wallets(session: SessionDep, user: CurrentUser) -> list[PasskeyWalletOut]:
    return await service.list_passkey_wallets(session, user)


@router.post("/wallets/passkey", response_model=PasskeyWalletOut, status_code=201)
async def create_passkey_wallet(
    data: PasskeyWalletCreate,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.WALLET_MANAGE))],
) -> PasskeyWalletOut:
    await hit("wallet:passkey", str(user.id), 5, 3600)
    return await service.create_passkey_wallet(session, user, data)


@router.get("/wallets/passkey/candidates", response_model=WalletCandidateOut, response_model_by_alias=True)
async def passkey_candidates(
    session: SessionDep,
    user: CurrentUser,
    key_id: Annotated[str, Query(min_length=8, max_length=1400, pattern=r"^[A-Za-z0-9_-]+$")],
) -> WalletCandidateOut:
    return await service.wallet_candidates(session, user, key_id)


@router.post("/wallets/{wallet_id}/primary", response_model=WalletOut)
async def set_primary_wallet(
    wallet_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.WALLET_MANAGE))],
) -> WalletOut:
    """Chooses the wallet payouts go to."""
    return await service.set_primary_wallet(session, user, wallet_id)


@admin_router.get("/sponsorship", response_model=SponsorshipOverview)
async def sponsorship_overview(
    session: SessionDep,
    _staff: Annotated[User, Depends(require_permission(Permission.TRANSACTION_VIEW_ALL))],
) -> SponsorshipOverview:
    return await service.sponsorship_overview(session)
