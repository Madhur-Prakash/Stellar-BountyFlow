"""Authentication use cases: registration, login, rotating refresh sessions, email verification, password reset."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import Conflict, NotAuthenticated, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_token,
    hash_password_async,
    hash_token,
    password_needs_rehash,
    split_refresh_token,
    utcnow,
    verify_password_async,
)
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.auth import repository as repo
from app.modules.auth.models import EmailVerificationToken, PasswordResetToken, UserSession
from app.modules.auth.schemas import RegisterRequest
from app.modules.notifications.models import NotificationPreference
from app.modules.users import repository as users_repo
from app.modules.users.models import User

logger = get_logger(__name__)


def normalize_email(email: str) -> str:
    return email.strip().lower()


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID


async def _start_session(
    session: AsyncSession, user: User, user_agent: str | None, ip: str | None
) -> IssuedTokens:
    settings = get_settings()
    secret = generate_token(32)
    user_session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        refresh_token_hash=hash_token(secret),
        expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl),
        last_used_at=utcnow(),
        user_agent=(user_agent or "")[:300] or None,
        ip_address=ip,
    )
    session.add(user_session)
    return IssuedTokens(
        access_token=create_access_token(user.id, user_session.id, user.role.value),
        refresh_token=f"{user_session.id}.{secret}",
        session_id=user_session.id,
    )


async def register(
    session: AsyncSession, data: RegisterRequest, user_agent: str | None, ip: str | None
) -> tuple[User, IssuedTokens]:
    normalized = normalize_email(data.email)
    if await users_repo.get_by_email(session, normalized):
        raise Conflict(
            "An account with this email already exists.", details=[{"field": "email", "message": "In use"}]
        )
    if await users_repo.username_taken(session, data.username):
        raise Conflict("That username is already taken.", details=[{"field": "username", "message": "Taken"}])
    user = User(
        id=uuid.uuid4(),
        email=data.email.strip(),
        normalized_email=normalized,
        password_hash=await hash_password_async(data.password),  # off the event loop (SEC-04)
        username=data.username,
        display_name=data.display_name,
        interests=[],
    )
    session.add(user)
    await session.flush()  # preferences reference users.id without an ORM relationship
    session.add(NotificationPreference(user_id=user.id, email_enabled=True, types={}))
    tokens = await _start_session(session, user, user_agent, ip)
    user.last_login_at = utcnow()
    audit.record(
        session,
        actor_id=user.id,
        action="user.registered",
        entity_type="user",
        entity_id=user.id,
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.USER_REGISTERED,
        aggregate_type="user",
        aggregate_id=user.id,
        actor_id=user.id,
        payload={"user_id": user.id},
    )
    add_event(
        session,
        event_type=EventType.EMAIL_VERIFICATION_REQUESTED,
        aggregate_type="user",
        aggregate_id=user.id,
        actor_id=user.id,
        payload={"user_id": user.id},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict("An account with this email or username already exists.") from exc
    await session.refresh(user)
    return user, tokens


async def login(
    session: AsyncSession, email: str, password: str, user_agent: str | None, ip: str | None
) -> tuple[User, IssuedTokens]:
    user = await users_repo.get_by_email(session, normalize_email(email))
    if user is None:
        await verify_password_async(DUMMY_PASSWORD_HASH, password)  # equalise timing (account enumeration)
        raise NotAuthenticated("Invalid email or password.", code="invalid_credentials")
    if not await verify_password_async(user.password_hash, password):
        raise NotAuthenticated("Invalid email or password.", code="invalid_credentials")
    if not user.is_active:
        raise NotAuthenticated("This account has been suspended.", code="account_suspended")
    if password_needs_rehash(user.password_hash):
        user.password_hash = await hash_password_async(password)
    tokens = await _start_session(session, user, user_agent, ip)
    user.last_login_at = utcnow()
    await session.commit()
    return user, tokens


async def refresh(session: AsyncSession, raw_token: str | None) -> tuple[User, IssuedTokens]:
    if not raw_token:
        raise NotAuthenticated("Refresh token missing.")
    session_id, secret = split_refresh_token(raw_token)
    user_session = await repo.get_session_by_id(session, session_id)
    if user_session is None:
        raise NotAuthenticated("Session not found.")
    now = utcnow()
    presented = hash_token(secret)
    if user_session.revoked_at is not None or user_session.expires_at <= now:
        raise NotAuthenticated("Session has ended.")
    if presented != user_session.refresh_token_hash:
        if user_session.previous_token_hash and presented == user_session.previous_token_hash:
            # A rotated-away token was replayed: assume theft and kill the session.
            user_session.revoked_at = now
            user_session.revoked_reason = "refresh_token_reuse"
            await session.commit()
            logger.warning("refresh_token_reuse_detected", session_id=str(session_id))
        raise NotAuthenticated("Invalid refresh token.")
    user = await session.get(User, user_session.user_id)
    if user is None or not user.is_active:
        raise NotAuthenticated("Account unavailable.")
    new_secret = generate_token(32)
    user_session.previous_token_hash = user_session.refresh_token_hash
    user_session.refresh_token_hash = hash_token(new_secret)
    user_session.last_used_at = now
    await session.commit()
    return user, IssuedTokens(
        access_token=create_access_token(user.id, user_session.id, user.role.value),
        refresh_token=f"{user_session.id}.{new_secret}",
        session_id=user_session.id,
    )


async def logout(session: AsyncSession, session_id: uuid.UUID | None, raw_refresh: str | None) -> None:
    target = session_id
    if target is None and raw_refresh:
        try:
            target, _ = split_refresh_token(raw_refresh)
        except NotAuthenticated:
            target = None
    if target is None:
        return
    user_session = await repo.get_session_by_id(session, target)
    if user_session and user_session.revoked_at is None:
        user_session.revoked_at = utcnow()
        user_session.revoked_reason = "logout"
        await session.commit()


async def list_sessions(session: AsyncSession, user: User) -> list[UserSession]:
    return await repo.active_sessions(session, user.id, utcnow())


async def revoke_session(session: AsyncSession, user: User, session_id: uuid.UUID) -> None:
    user_session = await repo.get_session_by_id(session, session_id)
    if user_session is None or user_session.user_id != user.id:
        raise NotFound("Session not found.")
    if user_session.revoked_at is None:
        user_session.revoked_at = utcnow()
        user_session.revoked_reason = "user_revoked"
        await session.commit()


# --- Email verification & password reset ---------------------------------------
# Raw tokens are created by the email worker at send time and are never placed on Kafka or in logs.


async def issue_email_verification_token(session: AsyncSession, user: User) -> str:
    now = utcnow()
    await repo.invalidate_open_verification_tokens(session, user.id, now)
    raw = generate_token(32)
    session.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(seconds=get_settings().email_verification_ttl),
        )
    )
    return raw


async def issue_password_reset_token(session: AsyncSession, user: User) -> str:
    now = utcnow()
    await repo.invalidate_open_reset_tokens(session, user.id, now)
    raw = generate_token(32)
    session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(seconds=get_settings().password_reset_ttl),
        )
    )
    return raw


async def verify_email(session: AsyncSession, raw_token: str) -> User:
    token = await repo.get_verification_token(session, hash_token(raw_token))
    now = utcnow()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise ValidationFailed("This verification link is invalid or has expired.", code="invalid_token")
    user = await session.get(User, token.user_id)
    if user is None:
        raise ValidationFailed("This verification link is invalid or has expired.", code="invalid_token")
    token.used_at = now
    if user.email_verified_at is None:
        user.email_verified_at = now
        audit.record(
            session,
            actor_id=user.id,
            action="user.email_verified",
            entity_type="user",
            entity_id=user.id,
            is_public=False,
        )
        add_event(
            session,
            event_type=EventType.USER_EMAIL_VERIFIED,
            aggregate_type="user",
            aggregate_id=user.id,
            actor_id=user.id,
            payload={"user_id": user.id},
        )
    await session.commit()
    return user


async def request_verification_email(session: AsyncSession, user: User) -> None:
    if user.email_verified_at is not None:
        return
    add_event(
        session,
        event_type=EventType.EMAIL_VERIFICATION_REQUESTED,
        aggregate_type="user",
        aggregate_id=user.id,
        actor_id=user.id,
        payload={"user_id": user.id},
    )
    await session.commit()


async def forgot_password(session: AsyncSession, email: str) -> None:
    user = await users_repo.get_by_email(session, normalize_email(email))
    if user is None or not user.is_active:
        return  # generic response either way
    add_event(
        session,
        event_type=EventType.PASSWORD_RESET_REQUESTED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"user_id": user.id},
    )
    await session.commit()


async def reset_password(session: AsyncSession, raw_token: str, new_password: str) -> None:
    token = await repo.get_reset_token(session, hash_token(raw_token))
    now = utcnow()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise ValidationFailed("This reset link is invalid or has expired.", code="invalid_token")
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise ValidationFailed("This reset link is invalid or has expired.", code="invalid_token")
    token.used_at = now
    user.password_hash = await hash_password_async(new_password)
    await repo.revoke_all_sessions(session, user.id, "password_reset", now)
    audit.record(
        session,
        actor_id=user.id,
        action="user.password_reset",
        entity_type="user",
        entity_id=user.id,
        is_public=False,
    )
    await session.commit()
