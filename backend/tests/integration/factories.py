"""Minimal ORM factories for integration tests. Each helper adds and flushes; callers commit."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.modules.applications.models import (
    ApplicationStatus,
    AssignmentStatus,
    BountyApplication,
    BountyAssignment,
)
from app.modules.bounties.models import Bounty, BountyStatus, Category, Difficulty
from app.modules.payments.models import BlockchainTransaction, BountyEscrow, EscrowState, TxStatus, TxType
from app.modules.users.models import Role, User


async def make_user(
    session: AsyncSession,
    *,
    role: Role = Role.USER,
    verified: bool = True,
    is_active: bool = True,
    **overrides: Any,
) -> User:
    handle = uuid.uuid4().hex[:10]
    fields: dict[str, Any] = {
        "id": uuid.uuid4(),
        "email": f"{handle}@example.com",
        "normalized_email": f"{handle}@example.com",
        "password_hash": "not-a-real-hash",
        "username": f"user_{handle}",
        "display_name": f"User {handle}",
        "interests": [],
        "role": role,
        "is_active": is_active,
        "email_verified_at": utcnow() if verified else None,
    }
    user = User(**{**fields, **overrides})
    session.add(user)
    await session.flush()
    return user


async def make_bounty(
    session: AsyncSession,
    requester: User,
    *,
    status: BountyStatus = BountyStatus.OPEN,
    published_at: datetime | None = None,
    reward: str = "100",
    **overrides: Any,
) -> Bounty:
    handle = uuid.uuid4().hex[:8]
    bounty = Bounty(
        id=uuid.uuid4(),
        requester_id=requester.id,
        title=f"Bounty {handle}",
        slug=f"bounty-{handle}",
        short_description="Short description",
        description="Long description",
        category=Category.DEVELOPMENT,
        difficulty=Difficulty.INTERMEDIATE,
        reward_amount=Decimal(reward),
        network="testnet",
        status=status,
        positions_available=1,
        metadata_={},
        published_at=published_at
        if published_at is not None
        else (utcnow() if status != BountyStatus.DRAFT else None),
        **overrides,
    )
    session.add(bounty)
    await session.flush()
    return bounty


async def make_escrow(session: AsyncSession, bounty: Bounty, *, funded: str = "0") -> BountyEscrow:
    escrow = BountyEscrow(
        bounty_id=bounty.id,
        network="testnet",
        onchain_bounty_id=uuid.uuid4().hex + uuid.uuid4().hex,
        asset_identifier="native",
        reward_per_position=bounty.reward_amount,
        positions=bounty.positions_available,
        required_amount=bounty.reward_amount * bounty.positions_available,
        funded_amount=Decimal(funded),
        paid_out_amount=Decimal(0),
        refunded_amount=Decimal(0),
        state=EscrowState.FUNDED if Decimal(funded) > 0 else EscrowState.AWAITING_FUNDING,
    )
    session.add(escrow)
    await session.flush()
    return escrow


async def make_tx(
    session: AsyncSession,
    *,
    bounty: Bounty | None,
    tx_type: TxType = TxType.PAYOUT,
    status: TxStatus = TxStatus.CONFIRMED,
    amount: str | None = "100",
    tx_hash: str | None = None,
    source: str | None = None,
    network: str = "testnet",
    confirmed_at: datetime | None = None,
) -> BlockchainTransaction:
    tx = BlockchainTransaction(
        bounty_id=bounty.id if bounty else None,
        transaction_hash=tx_hash if tx_hash is not None else uuid.uuid4().hex,
        transaction_type=tx_type,
        network=network,
        amount=Decimal(amount) if amount is not None else None,
        status=status,
        source_address=source or ("G" + uuid.uuid4().hex.upper() + "A" * 23)[:56],
        verification_metadata={},
        confirmed_at=confirmed_at or (utcnow() if status == TxStatus.CONFIRMED else None),
    )
    session.add(tx)
    await session.flush()
    return tx


async def make_application(
    session: AsyncSession,
    bounty: Bounty,
    contributor: User,
    *,
    status: ApplicationStatus = ApplicationStatus.PENDING,
) -> BountyApplication:
    application = BountyApplication(
        id=uuid.uuid4(),
        bounty_id=bounty.id,
        contributor_id=contributor.id,
        cover_message="I can do this",
        work_samples=[],
        status=status,
    )
    session.add(application)
    await session.flush()
    return application


async def make_assignment(
    session: AsyncSession,
    bounty: Bounty,
    contributor: User,
    *,
    status: AssignmentStatus = AssignmentStatus.COMPLETED,
) -> BountyAssignment:
    application = await make_application(session, bounty, contributor, status=ApplicationStatus.ACCEPTED)
    assignment = BountyAssignment(
        id=uuid.uuid4(),
        bounty_id=bounty.id,
        contributor_id=contributor.id,
        application_id=application.id,
        status=status,
        assigned_at=utcnow(),
        completed_at=utcnow() if status == AssignmentStatus.COMPLETED else None,
    )
    session.add(assignment)
    await session.flush()
    return assignment
