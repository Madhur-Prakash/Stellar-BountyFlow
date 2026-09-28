"""Database access for users, skills, and wallets."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import (
    ApplicationStatus,
    AssignmentStatus,
    BountyApplication,
    BountyAssignment,
)
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.payments.models import PaymentRecord, PaymentStatus
from app.modules.submissions.models import BountySubmission, SubmissionStatus
from app.modules.users.models import User, UserSkill, Wallet, WalletVerificationStatus


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(select(User).where(User.username == username.lower()))


async def get_by_email(session: AsyncSession, normalized_email: str) -> User | None:
    return await session.scalar(select(User).where(User.normalized_email == normalized_email))


async def username_taken(session: AsyncSession, username: str, exclude: uuid.UUID | None = None) -> bool:
    stmt: Select[uuid.UUID] = select(User.id).where(User.username == username)
    if exclude:
        stmt = stmt.where(User.id != exclude)
    return (await session.scalar(stmt)) is not None


def set_skills(user: User, skills: list[str]) -> None:
    existing = {s.skill_name: s for s in user.skills}
    user.skills = [existing.get(name) or UserSkill(skill_name=name) for name in skills]


def verified_wallets_stmt(user_id: uuid.UUID) -> Select[Wallet]:
    return (
        select(Wallet)
        .where(Wallet.user_id == user_id, Wallet.verification_status == WalletVerificationStatus.VERIFIED)
        .order_by(Wallet.verified_at)
    )


async def verified_wallets(session: AsyncSession, user_id: uuid.UUID) -> list[Wallet]:
    return list((await session.scalars(verified_wallets_stmt(user_id))).all())


async def has_verified_wallet(session: AsyncSession, user_id: uuid.UUID, network: str | None = None) -> bool:
    stmt = select(func.count(Wallet.id)).where(
        Wallet.user_id == user_id, Wallet.verification_status == WalletVerificationStatus.VERIFIED
    )
    if network:
        stmt = stmt.where(Wallet.network == network)
    return bool(await session.scalar(stmt))


async def find_verified_wallet(
    session: AsyncSession, user_id: uuid.UUID, address: str, network: str
) -> Wallet | None:
    return await session.scalar(
        select(Wallet).where(
            Wallet.user_id == user_id,
            Wallet.public_address == address,
            Wallet.network == network,
            Wallet.verification_status == WalletVerificationStatus.VERIFIED,
        )
    )


async def primary_wallet(session: AsyncSession, user_id: uuid.UUID, network: str) -> Wallet | None:
    return await session.scalar(
        select(Wallet)
        .where(
            Wallet.user_id == user_id,
            Wallet.network == network,
            Wallet.verification_status == WalletVerificationStatus.VERIFIED,
        )
        .order_by(Wallet.verified_at.desc())
        .limit(1)
    )


async def has_taken_first_action(session: AsyncSession, user_id: uuid.UUID) -> bool:
    created = await session.scalar(select(func.count(Bounty.id)).where(Bounty.requester_id == user_id))
    if created:
        return True
    applied = await session.scalar(
        select(func.count(BountyApplication.id)).where(BountyApplication.contributor_id == user_id)
    )
    return bool(applied)


async def compute_stats(session: AsyncSession, user_id: uuid.UUID) -> dict[str, object]:
    bounty_row = (
        await session.execute(
            select(
                func.count(Bounty.id).filter(Bounty.status != BountyStatus.DRAFT),
                func.count(Bounty.id).filter(Bounty.status == BountyStatus.COMPLETED),
            ).where(Bounty.requester_id == user_id, Bounty.is_hidden.is_(False))
        )
    ).one()
    app_row = (
        await session.execute(
            select(
                func.count(BountyApplication.id),
                func.count(BountyApplication.id).filter(
                    BountyApplication.status == ApplicationStatus.ACCEPTED
                ),
                func.count(BountyApplication.id).filter(
                    BountyApplication.status.in_([ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED])
                ),
            ).where(BountyApplication.contributor_id == user_id)
        )
    ).one()
    completed = await session.scalar(
        select(func.count(BountyAssignment.id)).where(
            BountyAssignment.contributor_id == user_id, BountyAssignment.status == AssignmentStatus.COMPLETED
        )
    )
    sub_row = (
        await session.execute(
            select(
                func.count(BountySubmission.id).filter(BountySubmission.status == SubmissionStatus.APPROVED),
                func.count(BountySubmission.id).filter(
                    BountySubmission.status.in_([SubmissionStatus.APPROVED, SubmissionStatus.REJECTED])
                ),
            ).where(BountySubmission.contributor_id == user_id)
        )
    ).one()
    confirmed = PaymentRecord.payment_status == PaymentStatus.CONFIRMED
    received = await session.scalar(
        select(func.coalesce(func.sum(PaymentRecord.amount), 0)).where(
            PaymentRecord.contributor_id == user_id, confirmed
        )
    )
    paid = await session.scalar(
        select(func.coalesce(func.sum(PaymentRecord.amount), 0))
        .join(Bounty, Bounty.id == PaymentRecord.bounty_id)
        .where(and_(Bounty.requester_id == user_id, confirmed))
    )
    total_apps, accepted, decided = app_row
    approved, reviewed = sub_row
    return {
        "bounties_created": bounty_row[0],
        "bounties_completed_as_requester": bounty_row[1],
        "contributions_completed": completed or 0,
        "applications_submitted": total_apps,
        "acceptance_rate": round(accepted / decided, 4) if decided else None,
        "approval_rate": round(approved / reviewed, 4) if reviewed else None,
        "total_rewards_received": Decimal(received or 0),
        "total_rewards_paid": Decimal(paid or 0),
    }
