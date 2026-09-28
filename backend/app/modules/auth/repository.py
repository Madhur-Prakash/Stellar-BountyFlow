"""Database access for sessions and single-use tokens."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import EmailVerificationToken, PasswordResetToken, UserSession


async def get_session_by_id(session: AsyncSession, session_id: uuid.UUID) -> UserSession | None:
    return await session.scalar(select(UserSession).where(UserSession.id == session_id).with_for_update())


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID, reason: str, now: datetime) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )


async def active_sessions(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> list[UserSession]:
    return list(
        (
            await session.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
                .order_by(UserSession.created_at.desc())
            )
        ).all()
    )


async def get_verification_token(session: AsyncSession, token_hash: str) -> EmailVerificationToken | None:
    return await session.scalar(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == token_hash)
        .with_for_update()
    )


async def get_reset_token(session: AsyncSession, token_hash: str) -> PasswordResetToken | None:
    return await session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash).with_for_update()
    )


async def invalidate_open_reset_tokens(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )


async def invalidate_open_verification_tokens(
    session: AsyncSession, user_id: uuid.UUID, now: datetime
) -> None:
    await session.execute(
        update(EmailVerificationToken)
        .where(EmailVerificationToken.user_id == user_id, EmailVerificationToken.used_at.is_(None))
        .values(used_at=now)
    )
