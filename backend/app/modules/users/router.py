"""User profile and wallet endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select

from app.core.rate_limit import hit
from app.core.rbac import Permission
from app.core.schemas import APIModel, OptionalMoney, Page, PageParams
from app.dependencies import CurrentUser, OptionalUser, SessionDep, require_permission
from app.modules.applications.models import AssignmentStatus, BountyAssignment
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty
from app.modules.bounties.schemas import BountySummary
from app.modules.payments.models import BlockchainTransaction, PaymentRecord, PaymentStatus
from app.modules.users import service
from app.modules.users.models import User
from app.modules.users.schemas import (
    Me,
    ProfileUpdate,
    PublicProfile,
    UserStats,
    WalletChallengeRequest,
    WalletChallengeResponse,
    WalletOut,
    WalletVerifyRequest,
)

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=Me)
async def get_me(user: CurrentUser, session: SessionDep) -> Me:
    return await service.build_me(session, user)


@router.patch("/users/me", response_model=Me)
async def update_me(data: ProfileUpdate, user: CurrentUser, session: SessionDep) -> Me:
    return await service.update_profile(session, user, data)


@router.post("/users/me/onboarding/complete", response_model=Me)
async def complete_onboarding(user: CurrentUser, session: SessionDep) -> Me:
    return await service.complete_onboarding(session, user)


@router.get("/users/{username}", response_model=PublicProfile)
async def public_profile(username: str, session: SessionDep) -> PublicProfile:
    return await service.get_public_profile(session, username)


@router.get("/users/{username}/bounties", response_model=Page[BountySummary])
async def user_bounties(
    username: str, session: SessionDep, viewer: OptionalUser, params: Annotated[PageParams, Depends()]
) -> Page[BountySummary]:
    user = await service.get_public_user(session, username)
    return await bounty_service.user_public_bounties(session, user.id, params, viewer)


class Contribution(APIModel):
    bounty: BountySummary
    completed_at: datetime
    amount: OptionalMoney
    transaction_hash: str | None


@router.get("/users/{username}/contributions", response_model=Page[Contribution])
async def contributions(
    username: str, session: SessionDep, viewer: OptionalUser, params: Annotated[PageParams, Depends()]
) -> Page[Contribution]:
    user = await service.get_public_user(session, username)
    base = (
        select(BountyAssignment, Bounty, PaymentRecord, BlockchainTransaction)
        .join(Bounty, Bounty.id == BountyAssignment.bounty_id)
        .outerjoin(
            PaymentRecord,
            (PaymentRecord.bounty_id == Bounty.id)
            & (PaymentRecord.contributor_id == BountyAssignment.contributor_id)
            & (PaymentRecord.payment_status == PaymentStatus.CONFIRMED),
        )
        .outerjoin(BlockchainTransaction, BlockchainTransaction.id == PaymentRecord.blockchain_transaction_id)
        .where(
            BountyAssignment.contributor_id == user.id,
            BountyAssignment.status == AssignmentStatus.COMPLETED,
            Bounty.is_hidden.is_(False),
        )
    )
    total = int(
        await session.scalar(
            select(func.count(BountyAssignment.id))
            .join(Bounty, Bounty.id == BountyAssignment.bounty_id)
            .where(
                BountyAssignment.contributor_id == user.id,
                BountyAssignment.status == AssignmentStatus.COMPLETED,
                Bounty.is_hidden.is_(False),
            )
        )
        or 0
    )
    rows = (
        (
            await session.execute(
                base.order_by(BountyAssignment.completed_at.desc())
                .offset(params.offset)
                .limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    summaries = await bounty_service.summaries(session, [r[1] for r in rows], viewer)
    items = [
        Contribution(
            bounty=summary,
            completed_at=assignment.completed_at or assignment.assigned_at,
            amount=payment.amount if payment else None,
            transaction_hash=tx.transaction_hash if tx else None,
        )
        for (assignment, _bounty, payment, tx), summary in zip(rows, summaries, strict=True)
    ]
    return Page[Contribution].build(items, total, params)


@router.get("/users/{username}/stats", response_model=UserStats)
async def user_stats(username: str, session: SessionDep) -> UserStats:
    return await service.get_stats(session, username)


# --- Wallets ----------------------------------------------------------------------------


@router.post("/wallets/challenge", response_model=WalletChallengeResponse, tags=["wallets"])
async def wallet_challenge(
    data: WalletChallengeRequest, user: Annotated[User, Depends(require_permission(Permission.WALLET_MANAGE))]
) -> WalletChallengeResponse:
    await hit("wallet:challenge", str(user.id), 20, 300)
    return await service.create_wallet_challenge(user, data.public_address)


@router.post("/wallets/verify", response_model=WalletOut, tags=["wallets"])
async def wallet_verify(
    data: WalletVerifyRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.WALLET_MANAGE))],
) -> WalletOut:
    await hit("wallet:verify", str(user.id), 20, 300)
    return await service.verify_wallet(session, user, data.public_address, data.signed_challenge_xdr)


@router.get("/wallets", response_model=list[WalletOut], tags=["wallets"])
async def list_wallets(session: SessionDep, user: CurrentUser) -> list[WalletOut]:
    return await service.list_wallets(session, user)


@router.delete("/wallets/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["wallets"])
async def delete_wallet(
    wallet_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.WALLET_MANAGE))],
) -> Response:
    await service.remove_wallet(session, user, wallet_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
