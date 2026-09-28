"""Funding, payout, chain-action, transaction, and payment endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from app.core.rate_limit import rate_limit
from app.core.schemas import Page, PageParams
from app.dependencies import CurrentUser, OptionalUser, SessionDep
from app.modules.payments import service
from app.modules.payments.schemas import (
    AliasSubmitRequest,
    BlockchainTransactionOut,
    ChainAction,
    FundingOut,
    FundingPrepareRequest,
    PaymentRecordOut,
    PayoutPrepareRequest,
    PreparedTransactionOut,
    PrepareRequest,
    SubmitRequest,
)

router = APIRouter(tags=["payments"])

_prepare_limit = [Depends(rate_limit("chain:prepare", 60, 300))]
_submit_limit = [Depends(rate_limit("chain:submit", 60, 300))]


@router.post(
    "/bounties/{bounty_id}/chain/prepare", response_model=PreparedTransactionOut, dependencies=_prepare_limit
)
async def prepare(
    bounty_id: uuid.UUID, data: PrepareRequest, session: SessionDep, user: CurrentUser
) -> PreparedTransactionOut:
    return await service.prepare_action(session, user, bounty_id, data)


@router.post(
    "/bounties/{bounty_id}/funding/prepare",
    response_model=PreparedTransactionOut,
    dependencies=_prepare_limit,
)
async def funding_prepare(
    bounty_id: uuid.UUID, data: FundingPrepareRequest, session: SessionDep, user: CurrentUser
) -> PreparedTransactionOut:
    req = PrepareRequest(action=ChainAction.FUND, wallet_address=data.wallet_address, amount=data.amount)
    return await service.prepare_action(session, user, bounty_id, req)


@router.post(
    "/bounties/{bounty_id}/funding/submit",
    response_model=BlockchainTransactionOut,
    dependencies=_submit_limit,
)
async def funding_submit(
    bounty_id: uuid.UUID, data: AliasSubmitRequest, session: SessionDep, user: CurrentUser
) -> BlockchainTransactionOut:
    return await service.submit_transaction(session, user, data.transaction_id, data.signed_xdr)


@router.get("/bounties/{bounty_id}/funding", response_model=FundingOut)
async def funding(bounty_id: uuid.UUID, session: SessionDep, viewer: OptionalUser) -> FundingOut:
    return await service.funding(session, bounty_id, viewer)


@router.post(
    "/bounties/{bounty_id}/payouts/prepare",
    response_model=PreparedTransactionOut,
    dependencies=_prepare_limit,
)
async def payout_prepare(
    bounty_id: uuid.UUID, data: PayoutPrepareRequest, session: SessionDep, user: CurrentUser
) -> PreparedTransactionOut:
    req = PrepareRequest(
        action=ChainAction.PAYOUT, wallet_address=data.wallet_address, submission_id=data.submission_id
    )
    return await service.prepare_action(session, user, bounty_id, req)


@router.post(
    "/bounties/{bounty_id}/payouts/submit",
    response_model=BlockchainTransactionOut,
    dependencies=_submit_limit,
)
async def payout_submit(
    bounty_id: uuid.UUID, data: AliasSubmitRequest, session: SessionDep, user: CurrentUser
) -> BlockchainTransactionOut:
    return await service.submit_transaction(session, user, data.transaction_id, data.signed_xdr)


@router.post(
    "/transactions/{transaction_id}/submit",
    response_model=BlockchainTransactionOut,
    dependencies=_submit_limit,
)
async def submit(
    transaction_id: uuid.UUID, data: SubmitRequest, session: SessionDep, user: CurrentUser
) -> BlockchainTransactionOut:
    return await service.submit_transaction(session, user, transaction_id, data.signed_xdr)


@router.get("/bounties/{bounty_id}/transactions", response_model=list[BlockchainTransactionOut])
async def bounty_transactions(
    bounty_id: uuid.UUID, session: SessionDep, viewer: OptionalUser
) -> list[BlockchainTransactionOut]:
    return await service.bounty_transactions(session, bounty_id, viewer)


@router.get("/transactions/me", response_model=Page[BlockchainTransactionOut])
async def my_transactions(
    session: SessionDep, user: CurrentUser, params: Annotated[PageParams, Depends()]
) -> Page[BlockchainTransactionOut]:
    return await service.my_transactions(session, user, params)


@router.get(
    "/transactions/{transaction_ref}",
    response_model=BlockchainTransactionOut,
    dependencies=[Depends(rate_limit("chain:poll", 240, 60))],
)
async def get_transaction(
    transaction_ref: str, session: SessionDep, viewer: OptionalUser
) -> BlockchainTransactionOut:
    return await service.get_transaction(session, transaction_ref, viewer)


@router.get("/payments/me", response_model=Page[PaymentRecordOut])
async def my_payments(
    session: SessionDep,
    user: CurrentUser,
    params: Annotated[PageParams, Depends()],
    direction: Literal["received", "sent"] = "received",
) -> Page[PaymentRecordOut]:
    return await service.my_payments(session, user, direction, params)
