"""Shared FastAPI dependencies: DB session, current user resolution, and RBAC permission guards."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, NotAuthenticated
from app.core.logging import bind_context
from app.core.rbac import Permission, has_permission
from app.core.security import ACCESS_COOKIE, decode_access_token, utcnow
from app.db.session import get_session
from app.modules.auth.models import UserSession
from app.modules.users.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


async def get_optional_user(request: Request, session: SessionDep) -> User | None:
    token = _extract_token(request)
    if not token:
        return None
    claims = decode_access_token(token)  # raises TokenExpired so the client refreshes and retries
    row = (
        await session.execute(
            select(User, UserSession)
            .join(UserSession, UserSession.user_id == User.id)
            .where(User.id == claims.user_id, UserSession.id == claims.session_id)
        )
    ).first()
    if row is None:
        raise NotAuthenticated("Session not found.")
    user, user_session = row
    if user_session.revoked_at is not None or user_session.expires_at <= utcnow():
        raise NotAuthenticated("Session has ended.")
    if not user.is_active:
        raise Forbidden("This account has been suspended.")
    request.state.user = user
    request.state.session_id = user_session.id
    bind_context(user_id=str(user.id))
    return user


async def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise NotAuthenticated("Authentication required.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


def require_permission(*required: Permission) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: the current user must hold every listed permission (see app.core.rbac)."""

    async def dependency(user: CurrentUser) -> User:
        missing = [p.value for p in required if not has_permission(user, p)]
        if missing:
            raise Forbidden(
                "You do not have permission to perform this action.",
                details={"required_permissions": missing},
            )
        return user

    return dependency


# Convenience aliases for the two staff tiers, expressed through permissions rather than role names.
ModeratorUser = Annotated[User, Depends(require_permission(Permission.BOUNTY_MODERATE))]
AdminUser = Annotated[User, Depends(require_permission(Permission.USER_MANAGE))]
