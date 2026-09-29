"""Reward asset endpoints: the public registry, trustline status and guidance, wallet-signed trustline and asset
contract operations, and admin asset management."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.rate_limit import hit
from app.core.rbac import Permission
from app.dependencies import CurrentUser, SessionDep, require_permission
from app.modules.assets import operations, service, views
from app.modules.assets.schemas import (
    AdminRewardAssetOut,
    AssetCreate,
    AssetOperationOut,
    AssetUpdate,
    BountyTrustlines,
    FundingReadiness,
    OperationSubmit,
    PreparedAssetOperation,
    RewardAssetOut,
    WalletAssets,
    WalletRequest,
)
from app.modules.users.models import User

router = APIRouter(tags=["assets"])

AssetAdmin = Annotated[User, Depends(require_permission(Permission.ASSET_MANAGE))]
WalletUser = Annotated[User, Depends(require_permission(Permission.WALLET_MANAGE))]


@router.get("/assets", response_model=list[RewardAssetOut])
async def list_assets(session: SessionDep) -> list[RewardAssetOut]:
    return await service.list_enabled(session)


@router.get("/assets/wallets", response_model=list[WalletAssets])
async def my_wallet_assets(session: SessionDep, user: CurrentUser) -> list[WalletAssets]:
    return await views.wallet_assets(session, user)


@router.post("/assets/{asset_id}/trustline/prepare", response_model=PreparedAssetOperation)
async def prepare_trustline(
    asset_id: uuid.UUID, data: WalletRequest, session: SessionDep, user: WalletUser
) -> PreparedAssetOperation:
    await hit("asset:trustline", str(user.id), 20, 300)
    return await operations.prepare_trustline(session, user, asset_id, data.wallet_address)


@router.post("/assets/operations/{operation_id}/submit", response_model=AssetOperationOut)
async def submit_operation(
    operation_id: uuid.UUID, data: OperationSubmit, session: SessionDep, user: CurrentUser
) -> AssetOperationOut:
    return await operations.submit(session, user, operation_id, data.signed_xdr)


@router.get("/assets/operations/{operation_id}", response_model=AssetOperationOut)
async def get_operation(operation_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> AssetOperationOut:
    return await operations.get_operation(session, user, operation_id)


@router.get("/bounties/{bounty_id}/trustlines", response_model=BountyTrustlines)
async def bounty_trustlines(bounty_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> BountyTrustlines:
    return await views.bounty_trustlines(session, user, bounty_id)


@router.get("/bounties/{bounty_id}/funding/readiness", response_model=FundingReadiness)
async def funding_readiness(
    bounty_id: uuid.UUID,
    session: SessionDep,
    user: CurrentUser,
    wallet_address: Annotated[str, Query(min_length=56, max_length=56)],
) -> FundingReadiness:
    return await views.funding_readiness(session, user, bounty_id, wallet_address)


# --- Admin ---------------------------------------------------------------------------------------------


@router.get("/admin/assets", response_model=list[AdminRewardAssetOut], tags=["admin"])
async def admin_list_assets(session: SessionDep, user: AssetAdmin) -> list[AdminRewardAssetOut]:
    return await service.admin_list(session)


@router.post(
    "/admin/assets",
    response_model=AdminRewardAssetOut,
    status_code=status.HTTP_201_CREATED,
    tags=["admin"],
)
async def admin_create_asset(data: AssetCreate, session: SessionDep, user: AssetAdmin) -> AdminRewardAssetOut:
    await hit("asset:create", str(user.id), 30, 3600)
    return await service.admin_create(session, user, data)


@router.patch("/admin/assets/{asset_id}", response_model=AdminRewardAssetOut, tags=["admin"])
async def admin_update_asset(
    asset_id: uuid.UUID, data: AssetUpdate, session: SessionDep, user: AssetAdmin
) -> AdminRewardAssetOut:
    return await service.admin_update(session, user, asset_id, data)


@router.post("/admin/assets/{asset_id}/verify", response_model=AdminRewardAssetOut, tags=["admin"])
async def admin_verify_asset(
    asset_id: uuid.UUID, session: SessionDep, user: AssetAdmin
) -> AdminRewardAssetOut:
    return await service.admin_verify(session, user, asset_id)


@router.post("/admin/assets/{asset_id}/deploy/prepare", response_model=PreparedAssetOperation, tags=["admin"])
async def admin_prepare_deploy(
    asset_id: uuid.UUID, data: WalletRequest, session: SessionDep, user: AssetAdmin
) -> PreparedAssetOperation:
    return await operations.prepare_deploy(session, user, asset_id, data.wallet_address)
