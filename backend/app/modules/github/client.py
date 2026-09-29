"""GitHub REST API client.

* Works unauthenticated (60 requests an hour per IP). ``GITHUB_TOKEN`` raises that to 5,000 and is only sent to
  the API host.
* Responses are cached in Redis in a reduced shape, with their ETag. A fresh entry is served without a request;
  a stale one is revalidated with ``If-None-Match`` (a 304 costs no body), and is served as-is while GitHub is
  unreachable or rate-limited.
* When the rate limit is exhausted (or GitHub asks to slow down with ``Retry-After``) every caller backs off
  until the reset time, shared through Redis, instead of spending more requests.
* The transport is injectable (``transport.set_transport``) so tests replay recorded real responses.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.cache import keys
from app.cache.redis import cache_get_json, cache_set_json, get_redis
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.github import transport as github_transport

logger = get_logger(__name__)

API_VERSION = "2022-11-28"
USER_AGENT = "BountyFlow (+https://github.com/Madhur-Prakash/Stellar-BountyFlow)"
BACKOFF_KEY = f"{keys.PREFIX}:github:backoff-until"
# Longest a cached response is kept for stale fallback and revalidation.
KEEP_SECONDS = 6 * 3600
MAX_GIST_CONTENT = 100_000

Shape = Callable[[Any], Any]


class GitHubError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class GitHubNotFound(GitHubError):
    """The resource does not exist, or it is private (GitHub answers 404 for both)."""


class GitHubUnavailable(GitHubError):
    """GitHub could not be reached, failed, or is rate-limiting us. ``retry_at`` is when to try again."""

    def __init__(self, message: str, retry_at: datetime | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


def _cache_key(url: str) -> str:
    return f"{keys.PREFIX}:github:resp:{hashlib.sha256(url.encode()).hexdigest()[:40]}"


def _epoch(value: float) -> datetime:
    return datetime.fromtimestamp(value, UTC)


# --- Response shapes (what BountyFlow keeps of each resource) ------------------------------------------


def shape_pull(pr: Any) -> dict[str, Any]:
    base = pr.get("base") or {}
    base_repo = base.get("repo") or {}
    head = pr.get("head") or {}
    user = pr.get("user") or {}
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "merged": bool(pr.get("merged")),
        "merged_at": pr.get("merged_at"),
        "draft": bool(pr.get("draft")),
        "html_url": pr.get("html_url"),
        "user": {"login": user.get("login"), "id": user.get("id"), "type": user.get("type")},
        "head": {
            "sha": head.get("sha"),
            "ref": head.get("ref"),
            "repo": (head.get("repo") or {}).get("full_name"),
        },
        "base": {
            "ref": base.get("ref"),
            "repo": {"id": base_repo.get("id"), "full_name": base_repo.get("full_name")},
        },
    }


def shape_repo(repo: Any) -> dict[str, Any]:
    return {"id": repo.get("id"), "full_name": repo.get("full_name"), "html_url": repo.get("html_url")}


def shape_check_runs(body: Any) -> dict[str, Any]:
    runs = [
        {"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion")}
        for r in body.get("check_runs") or []
    ]
    return {"total_count": body.get("total_count", len(runs)), "check_runs": runs}


def shape_status(body: Any) -> dict[str, Any]:
    statuses = [{"context": s.get("context"), "state": s.get("state")} for s in body.get("statuses") or []]
    return {
        "state": body.get("state"),
        "total_count": body.get("total_count", len(statuses)),
        "statuses": statuses,
    }


def shape_user(user: Any) -> dict[str, Any]:
    return {
        "login": user.get("login"),
        "id": user.get("id"),
        "avatar_url": user.get("avatar_url"),
        "html_url": user.get("html_url"),
        "type": user.get("type"),
    }


def shape_gist(gist: Any) -> dict[str, Any]:
    files = {
        name: {
            "content": str(f.get("content") or "")[:MAX_GIST_CONTENT],
            "truncated": bool(f.get("truncated")),
        }
        for name, f in (gist.get("files") or {}).items()
    }
    return {
        "id": gist.get("id"),
        "html_url": gist.get("html_url"),
        "public": bool(gist.get("public")),
        "owner": shape_user(gist.get("owner") or {}),
        "files": files,
    }


# --- Client ---------------------------------------------------------------------------------------


class GitHubClient:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self._transport = transport

    @property
    def authenticated(self) -> bool:
        return bool(self.settings.github_token)

    def _http(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=base_url,
            transport=self._transport or github_transport.get_transport(),
            timeout=self.settings.github_timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,  # renamed or transferred repositories answer 301 to the new location
        )

    def _api_headers(self, token: str | None) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _backoff_until(self) -> float | None:
        try:
            raw = await get_redis().get(BACKOFF_KEY)
        except Exception:
            return None
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    async def _back_off(self, until: float, reason: str) -> None:
        logger.warning("github_rate_limited", reason=reason, until=_epoch(until).isoformat())
        try:
            await get_redis().set(BACKOFF_KEY, str(until), ex=max(1, int(until - time.time()) + 1))
        except Exception as exc:
            logger.warning("github_backoff_store_failed", error=str(exc))

    async def _check_rate_limit(self, res: httpx.Response) -> bool:
        """Records a backoff when this response says we are rate-limited. Returns True when it did."""
        now = time.time()
        retry_after = res.headers.get("retry-after")
        remaining = res.headers.get("x-ratelimit-remaining")
        reset = res.headers.get("x-ratelimit-reset")
        if res.status_code in (403, 429) and retry_after and retry_after.isdigit():
            await self._back_off(now + int(retry_after), "retry_after")
            return True
        if remaining == "0" and reset and reset.isdigit():
            await self._back_off(max(now + 1, float(reset)), "limit_exhausted")
            return res.status_code in (403, 429)
        if res.status_code == 429:
            await self._back_off(now + 60, "too_many_requests")
            return True
        return False

    async def get_json(
        self,
        path: str,
        *,
        shape: Shape,
        fresh_seconds: int = 30,
        params: dict[str, str] | None = None,
        cache: bool = True,
    ) -> Any:
        """GET an API resource (shaped). Raises GitHubNotFound or GitHubUnavailable."""
        query = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        key = _cache_key(f"{self.settings.github_api_url}{path}?{query}")
        cached = await cache_get_json(key) if cache else None
        now = time.time()
        if cached is not None and now - float(cached.get("at", 0)) < fresh_seconds:
            return self._from_cache(cached)
        until = await self._backoff_until()
        if until is not None and until > now:
            if cached is not None:
                return self._from_cache(cached)
            raise GitHubUnavailable(
                "GitHub's rate limit is reached. The check will run again later.", _epoch(until)
            )

        headers = self._api_headers(self.settings.github_token)
        if cached is not None and cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])
        try:
            async with self._http(self.settings.github_api_url) as http:
                res = await http.get(path, params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("github_request_failed", path=path, error=type(exc).__name__)
            if cached is not None:
                return self._from_cache(cached)
            raise GitHubUnavailable("GitHub could not be reached.") from exc

        limited = await self._check_rate_limit(res)
        if res.status_code == 304 and cached is not None:
            cached["at"] = now
            await cache_set_json(key, cached, KEEP_SECONDS)
            return self._from_cache(cached)
        if res.status_code in (404, 410) or (res.status_code == 403 and not limited):
            # 403 without a rate limit means the resource is not readable (blocked, or DMCA-disabled).
            if cache:
                await cache_set_json(key, {"at": now, "status": 404, "etag": None, "body": None}, 120)
            raise GitHubNotFound("Not found on GitHub.")
        if limited or res.status_code >= 500 or res.status_code == 429:
            if cached is not None:
                return self._from_cache(cached)
            until = await self._backoff_until()
            raise GitHubUnavailable(
                "GitHub's rate limit is reached. The check will run again later."
                if limited
                else "GitHub returned an error. The check will run again later.",
                _epoch(until) if until else None,
            )
        if res.status_code != 200:
            raise GitHubNotFound(f"GitHub rejected the request ({res.status_code}).")
        try:
            body = shape(res.json())
        except (ValueError, AttributeError, TypeError) as exc:
            raise GitHubUnavailable("GitHub returned an unexpected response.") from exc
        if cache:
            await cache_set_json(
                key, {"at": now, "status": 200, "etag": res.headers.get("etag"), "body": body}, KEEP_SECONDS
            )
        return body

    @staticmethod
    def _from_cache(cached: dict[str, Any]) -> Any:
        if cached.get("status") == 404:
            raise GitHubNotFound("Not found on GitHub.")
        return cached.get("body")

    # --- Resources ----------------------------------------------------------------------------------

    async def get_pull(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return await self.get_json(
            f"/repos/{owner}/{repo}/pulls/{number}", shape=shape_pull, fresh_seconds=30
        )

    async def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        return await self.get_json(f"/repos/{owner}/{repo}", shape=shape_repo, fresh_seconds=3600)

    async def get_check_runs(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        return await self.get_json(
            f"/repos/{owner}/{repo}/commits/{sha}/check-runs",
            shape=shape_check_runs,
            params={"per_page": "100"},
            fresh_seconds=30,
        )

    async def get_combined_status(self, owner: str, repo: str, sha: str) -> dict[str, Any]:
        return await self.get_json(
            f"/repos/{owner}/{repo}/commits/{sha}/status", shape=shape_status, fresh_seconds=30
        )

    async def get_gist(self, gist_id: str) -> dict[str, Any]:
        # Never cached: the user creates the gist moments before asking us to read it.
        return await self.get_json(f"/gists/{gist_id}", shape=shape_gist, cache=False)

    # --- OAuth (optional "Connect with GitHub") -------------------------------------------------------

    async def exchange_oauth_code(self, code: str, redirect_uri: str) -> str:
        """Trade an authorization code for a user access token (used once to read the login, then dropped)."""
        s = self.settings
        try:
            async with self._http(s.github_oauth_url) as http:
                res = await http.post(
                    "/login/oauth/access_token",
                    headers={"Accept": "application/json"},
                    data={
                        "client_id": s.github_client_id or "",
                        "client_secret": s.github_client_secret or "",
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                )
        except httpx.HTTPError as exc:
            raise GitHubUnavailable("GitHub could not be reached.") from exc
        if res.status_code >= 500:
            raise GitHubUnavailable("GitHub returned an error. Try again in a moment.")
        try:
            body = res.json()
        except ValueError as exc:
            raise GitHubUnavailable("GitHub returned an unexpected response.") from exc
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise GitHubError("GitHub did not accept the sign-in. Start again from Settings.")
        return str(token)

    async def get_authenticated_user(self, access_token: str) -> dict[str, Any]:
        try:
            async with self._http(self.settings.github_api_url) as http:
                res = await http.get("/user", headers=self._api_headers(access_token))
        except httpx.HTTPError as exc:
            raise GitHubUnavailable("GitHub could not be reached.") from exc
        if res.status_code != 200:
            raise GitHubError("GitHub did not return the signed-in account.")
        return shape_user(res.json())
