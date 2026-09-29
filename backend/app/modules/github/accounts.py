"""Linking a GitHub account to a BountyFlow account.

**Gist proof (always available, no OAuth app needed).** ``POST /github/account/challenge`` issues a one-time
challenge bound to the signed-in user and the GitHub login they claim (Redis, 30 minutes). The user saves it in a
gist; ``POST /github/account/verify-gist`` fetches that gist through the GitHub REST API and links the account
only if the gist's owner is the claimed login and a file contains the exact challenge. The verified numeric
GitHub id is stored, so a later rename does not break the link, and one GitHub account can be linked to only one
BountyFlow account.

**OAuth (optional).** With ``GITHUB_CLIENT_ID`` and ``GITHUB_CLIENT_SECRET`` set, "Connect with GitHub" runs the
web flow with a single-use ``state`` bound to the user. The access token is used once to read the login and id,
and is never stored.
"""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.exceptions import AppError, Conflict, NotFound, ServiceUnavailable, ValidationFailed
from app.core.logging import get_logger
from app.core.rate_limit import hit
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.github import service as pr_service
from app.modules.github.client import GitHubClient, GitHubError, GitHubNotFound, GitHubUnavailable
from app.modules.github.models import GitHubAccount, GitHubLinkMethod
from app.modules.github.schemas import (
    ChallengeOut,
    GitHubAccountOut,
    GitHubConfigOut,
    OAuthStartOut,
    PublicGitHubAccount,
)
from app.modules.github.urls import parse_gist_id
from app.modules.github.verification import gist_proves_ownership
from app.modules.users.models import User

logger = get_logger(__name__)

CHALLENGE_TTL = timedelta(minutes=30)
OAUTH_STATE_TTL = timedelta(minutes=10)
CHALLENGE_FILENAME = "bountyflow-verification.txt"
OAUTH_CALLBACK_PATH = "/app/settings/github/callback"


def _challenge_key(user_id: object) -> str:
    return f"{keys.PREFIX}:github:challenge:{user_id}"


def _oauth_state_key(state: str) -> str:
    return f"{keys.PREFIX}:github:oauth-state:{state}"


def profile_url(login: str) -> str:
    return f"https://github.com/{login}"


def account_out(account: GitHubAccount) -> GitHubAccountOut:
    return GitHubAccountOut(
        github_id=account.github_id,
        login=account.login,
        avatar_url=account.avatar_url,
        profile_url=profile_url(account.login),
        method=account.method,
        proof_url=account.proof_url,
        verified_at=account.verified_at,
    )


def config() -> GitHubConfigOut:
    s = get_settings()
    return GitHubConfigOut(
        oauth_enabled=bool(s.github_client_id and s.github_client_secret),
        webhook_enabled=bool(s.github_webhook_secret),
        authenticated_api=bool(s.github_token),
    )


async def get_account(session: AsyncSession, user: User) -> GitHubAccountOut | None:
    account = await session.get(GitHubAccount, user.id)
    return account_out(account) if account else None


async def get_public_account(session: AsyncSession, username: str) -> PublicGitHubAccount | None:
    user = await session.scalar(select(User).where(User.username == username.lower()))
    if user is None or not user.is_active:
        raise NotFound("User not found.")
    account = await session.get(GitHubAccount, user.id)
    if account is None:
        return None
    return PublicGitHubAccount(
        login=account.login,
        avatar_url=account.avatar_url,
        profile_url=profile_url(account.login),
        verified_at=account.verified_at,
    )


# --- Gist proof ------------------------------------------------------------------------------------


async def issue_challenge(user: User, login: str) -> ChallengeOut:
    await hit("github:challenge", str(user.id), 10, 900)
    challenge = f"bountyflow:{user.username}:{secrets.token_hex(16)}"
    expires_at = utcnow() + CHALLENGE_TTL
    try:
        await get_redis().set(
            _challenge_key(user.id),
            json.dumps({"login": login, "challenge": challenge}),
            ex=int(CHALLENGE_TTL.total_seconds()),
        )
    except Exception as exc:  # fail closed: without the stored challenge nothing can be verified
        raise ServiceUnavailable("Account linking is temporarily unavailable. Try again shortly.") from exc
    return ChallengeOut(login=login, challenge=challenge, filename=CHALLENGE_FILENAME, expires_at=expires_at)


async def _pending_challenge(user: User) -> dict[str, str]:
    try:
        raw = await get_redis().get(_challenge_key(user.id))
    except Exception as exc:
        raise ServiceUnavailable("Account linking is temporarily unavailable. Try again shortly.") from exc
    if not raw:
        raise ValidationFailed(
            "The verification text has expired. Start again to get a new one.", code="challenge_expired"
        )
    data = json.loads(raw)
    return {"login": str(data["login"]), "challenge": str(data["challenge"])}


async def verify_gist(session: AsyncSession, user: User, gist_url: str) -> GitHubAccountOut:
    await hit("github:verify", str(user.id), 20, 900)
    pending = await _pending_challenge(user)
    gist_id = parse_gist_id(gist_url)
    if gist_id is None:
        raise ValidationFailed(
            "Paste the gist's URL, like https://gist.github.com/you/0123abcd.",
            details=[{"field": "gist_url", "message": "Not a gist URL"}],
        )
    client = GitHubClient()
    try:
        gist = await client.get_gist(gist_id)
    except GitHubNotFound as exc:
        raise ValidationFailed(
            "That gist was not found. Check the URL and that the gist is saved.", code="gist_not_found"
        ) from exc
    except GitHubUnavailable as exc:
        raise ServiceUnavailable(exc.message) from exc
    problem = gist_proves_ownership(gist, login=pending["login"], challenge=pending["challenge"])
    if problem is not None:
        raise ValidationFailed(problem, code="gist_not_verified")
    owner = gist["owner"]
    account = await _link(
        session,
        user,
        github_id=int(owner["id"]),
        login=str(owner["login"]),
        avatar_url=owner.get("avatar_url"),
        method=GitHubLinkMethod.GIST,
        proof_url=gist.get("html_url"),
    )
    try:
        await get_redis().delete(_challenge_key(user.id))
    except Exception as exc:
        logger.warning("github_challenge_clear_failed", error=str(exc))
    return account


# --- OAuth (optional) ------------------------------------------------------------------------------


def _redirect_uri() -> str:
    return get_settings().frontend_url.rstrip("/") + OAUTH_CALLBACK_PATH


async def start_oauth(user: User) -> OAuthStartOut:
    s = get_settings()
    if not (s.github_client_id and s.github_client_secret):
        raise AppError(
            "Connecting with GitHub is not configured on this server. Verify with a gist instead.",
            code="github_oauth_disabled",
        )
    await hit("github:oauth", str(user.id), 10, 900)
    state = secrets.token_urlsafe(24)
    try:
        await get_redis().set(_oauth_state_key(state), str(user.id), ex=int(OAUTH_STATE_TTL.total_seconds()))
    except Exception as exc:
        raise ServiceUnavailable("Account linking is temporarily unavailable. Try again shortly.") from exc
    query = urlencode(
        {
            "client_id": s.github_client_id,
            "redirect_uri": _redirect_uri(),
            "state": state,
            "allow_signup": "false",
        }
    )
    return OAuthStartOut(authorize_url=f"{s.github_oauth_url.rstrip('/')}/login/oauth/authorize?{query}")


async def complete_oauth(session: AsyncSession, user: User, code: str, state: str) -> GitHubAccountOut:
    s = get_settings()
    if not (s.github_client_id and s.github_client_secret):
        raise AppError(
            "Connecting with GitHub is not configured on this server.", code="github_oauth_disabled"
        )
    try:
        owner = await get_redis().getdel(_oauth_state_key(state))  # single use, even when the exchange fails
    except Exception as exc:
        raise ServiceUnavailable("Account linking is temporarily unavailable. Try again shortly.") from exc
    if owner != str(user.id):
        raise ValidationFailed(
            "This GitHub sign-in is no longer valid. Start again from Settings.", code="oauth_state"
        )
    client = GitHubClient()
    try:
        token = await client.exchange_oauth_code(code, _redirect_uri())
        gh_user = await client.get_authenticated_user(token)
    except GitHubUnavailable as exc:
        raise ServiceUnavailable(exc.message) from exc
    except GitHubError as exc:
        raise ValidationFailed(exc.message, code="oauth_failed") from exc
    return await _link(
        session,
        user,
        github_id=int(gh_user["id"]),
        login=str(gh_user["login"]),
        avatar_url=gh_user.get("avatar_url"),
        method=GitHubLinkMethod.OAUTH,
        proof_url=None,
    )


# --- Link / unlink ---------------------------------------------------------------------------------


async def _link(
    session: AsyncSession,
    user: User,
    *,
    github_id: int,
    login: str,
    avatar_url: str | None,
    method: GitHubLinkMethod,
    proof_url: str | None,
) -> GitHubAccountOut:
    taken = await session.scalar(select(GitHubAccount).where(GitHubAccount.github_id == github_id))
    if taken is not None and taken.user_id != user.id:
        raise Conflict(
            f"@{login} is already linked to another BountyFlow account.", code="github_account_taken"
        )
    account = await session.get(GitHubAccount, user.id, with_for_update=True)
    now = utcnow()
    if account is None:
        account = GitHubAccount(
            user_id=user.id, github_id=github_id, login=login, method=method, verified_at=now
        )
        session.add(account)
    account.github_id = github_id
    account.login = login
    account.avatar_url = avatar_url
    account.method = method
    account.proof_url = proof_url
    account.verified_at = now
    await session.flush()
    await pr_service.reevaluate_authorship(session, user.id, account)
    audit.record(
        session,
        actor_id=user.id,
        action="github.account_linked",
        entity_type="user",
        entity_id=user.id,
        metadata={"login": login, "github_id": github_id, "method": method.value},
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.GITHUB_ACCOUNT_LINKED,
        aggregate_type="user",
        aggregate_id=user.id,
        actor_id=user.id,
        payload={"user_id": user.id, "github_id": github_id, "login": login},
    )
    await session.commit()
    await session.refresh(account)
    logger.info("github_account_linked", user_id=str(user.id), method=method.value)
    return account_out(account)


async def unlink(session: AsyncSession, user: User) -> None:
    account = await session.get(GitHubAccount, user.id, with_for_update=True)
    if account is None:
        raise NotFound("No GitHub account is linked.")
    github_id, login = account.github_id, account.login
    await session.delete(account)
    await session.flush()
    await pr_service.reevaluate_authorship(session, user.id, None)
    audit.record(
        session,
        actor_id=user.id,
        action="github.account_unlinked",
        entity_type="user",
        entity_id=user.id,
        metadata={"login": login, "github_id": github_id},
        is_public=False,
    )
    add_event(
        session,
        event_type=EventType.GITHUB_ACCOUNT_UNLINKED,
        aggregate_type="user",
        aggregate_id=user.id,
        actor_id=user.id,
        payload={"user_id": user.id, "github_id": github_id, "login": login},
    )
    await session.commit()
