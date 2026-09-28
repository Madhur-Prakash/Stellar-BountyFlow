"""Staff endpoints for bounty moderation, dispute queues, and transaction monitoring.

User management, reports, audit logs and the overview live in `router_users.py`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.core.rbac import Permission
from app.core.schemas import Page, PageParams
from app.dependencies import SessionDep, require_permission
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.bounties.repository import contains_pattern
from app.modules.bounties.schemas import BountyDetail, BountySummary, ModerateRequest
from app.modules.disputes import service as dispute_service
from app.modules.disputes.models import DisputeStatus
from app.modules.disputes.schemas import DisputeOut
from app.modules.payments import service as payment_service
from app.modules.payments.models import TxStatus, TxType
from app.modules.payments.schemas import BlockchainTransactionOut
from app.modules.users.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/bounties", response_model=Page[BountySummary])
async def list_bounties(
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.BOUNTY_VIEW_ALL))],
    params: Annotated[PageParams, Depends()],
    q: Annotated[str | None, Query(max_length=200)] = None,
    status_filter: Annotated[BountyStatus | None, Query(alias="status")] = None,
    hidden: bool | None = None,
) -> Page[BountySummary]:
    base = select(Bounty)
    if q:
        pattern = contains_pattern(q.strip())  # wildcards in the query are literals
        base = base.where(
            or_(Bounty.title.ilike(pattern, escape="\\"), Bounty.slug.ilike(pattern, escape="\\"))
        )
    if status_filter:
        base = base.where(Bounty.status == status_filter)
    if hidden is not None:
        base = base.where(Bounty.is_hidden.is_(hidden))
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        (
            await session.scalars(
                base.order_by(Bounty.created_at.desc()).offset(params.offset).limit(params.page_size)
            )
        )
        .unique()
        .all()
    )
    return Page[BountySummary].build(await bounty_service.summaries(session, rows, user), total, params)


@router.post("/bounties/{bounty_id}/moderate", response_model=BountyDetail)
async def moderate(
    bounty_id: uuid.UUID,
    data: ModerateRequest,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.BOUNTY_MODERATE))],
) -> BountyDetail:
    return await bounty_service.moderate(session, user, bounty_id, data.action, data.reason)


@router.post("/bounties/{bounty_id}/reconcile", response_model=BountyDetail)
async def reconcile(
    bounty_id: uuid.UUID,
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.TRANSACTION_VIEW_ALL))],
) -> BountyDetail:
    """Re-reads the escrow from the contract and overwrites the cached DB view with chain truth."""
    await payment_service.reconcile_bounty(session, bounty_id)
    bounty = await bounty_service.load_for_update(session, bounty_id)
    await session.commit()
    return await bounty_service.detail(session, bounty, user)


@router.get("/disputes", response_model=Page[DisputeOut])
async def list_disputes(
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.DISPUTE_VIEW_ALL))],
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[DisputeStatus | None, Query(alias="status")] = None,
) -> Page[DisputeOut]:
    return await dispute_service.list_all(session, status_filter, params)


@router.get("/transactions", response_model=Page[BlockchainTransactionOut])
async def list_transactions(
    session: SessionDep,
    user: Annotated[User, Depends(require_permission(Permission.TRANSACTION_VIEW_ALL))],
    params: Annotated[PageParams, Depends()],
    status_filter: Annotated[TxStatus | None, Query(alias="status")] = None,
    tx_type: Annotated[TxType | None, Query(alias="type")] = None,
) -> Page[BlockchainTransactionOut]:
    return await payment_service.all_transactions(session, status_filter, tx_type, params)
