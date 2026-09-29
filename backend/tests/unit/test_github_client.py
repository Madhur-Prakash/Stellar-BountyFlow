"""GitHub client: caching, conditional requests, 404s and rate-limit backoff, driven through an injected transport
that replays recorded real responses (tests/support/github_fixtures.py)."""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable

import httpx
import pytest

from app.core.config import Settings
from app.modules.github.client import BACKOFF_KEY, GitHubClient, GitHubNotFound, GitHubUnavailable
from tests.support.github_fixtures import handler as fixture_handler
from tests.support.github_fixtures import register_gist

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]


class Recorder:
    """Wraps a handler and records every request that reached "GitHub"."""

    def __init__(self, inner: Handler = fixture_handler) -> None:
        self.inner = inner
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self.inner(request)

    def client(self, **settings: object) -> GitHubClient:
        return GitHubClient(Settings(**settings), transport=httpx.MockTransport(self))  # type: ignore[arg-type]


async def test_pull_request_is_fetched_shaped_and_cached(fake_redis: object) -> None:
    rec = Recorder()
    client = rec.client()
    pr = await client.get_pull("stellar", "js-stellar-sdk", 1744)
    assert pr["merged"] is True and pr["user"]["login"] == "Ryang-21"
    assert set(pr) >= {"number", "title", "state", "merged_at", "head", "base", "user"}
    assert "body" not in pr  # only what verification needs is kept
    again = await client.get_pull("stellar", "js-stellar-sdk", 1744)
    assert again == pr
    assert len(rec.requests) == 1  # the fresh cache answered the second call
    sent = rec.requests[0]
    assert sent.headers["accept"] == "application/vnd.github+json"
    assert sent.headers["x-github-api-version"] == "2022-11-28"
    assert "authorization" not in sent.headers


async def test_stale_entries_are_revalidated_with_the_etag(fake_redis: object) -> None:
    rec = Recorder()
    client = rec.client()
    await client.get_json("/repos/stellar/js-stellar-sdk/pulls/1744", shape=lambda b: b, fresh_seconds=0)
    await client.get_json("/repos/stellar/js-stellar-sdk/pulls/1744", shape=lambda b: b, fresh_seconds=0)
    assert len(rec.requests) == 2
    assert rec.requests[1].headers["if-none-match"].startswith('"bc761d06')  # the recorded ETag -> 304


async def test_token_is_sent_only_when_configured(fake_redis: object) -> None:
    rec = Recorder()
    await rec.client(github_token="ghp_test_only").get_repo("stellar", "js-stellar-sdk")
    assert rec.requests[0].headers["authorization"] == "Bearer ghp_test_only"


async def test_missing_pull_request_raises_not_found_and_is_negatively_cached(fake_redis: object) -> None:
    rec = Recorder()
    client = rec.client()
    for _ in range(2):
        with pytest.raises(GitHubNotFound):
            await client.get_pull("stellar", "js-stellar-sdk", 999999)
    assert len(rec.requests) == 1


async def test_exhausted_rate_limit_backs_off_every_caller(fake_redis: object) -> None:
    reset = int(time.time()) + 600

    async def limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
            json={"message": "API rate limit exceeded", "documentation_url": "https://docs.github.com/rest"},
        )

    rec = Recorder(limited)
    client = rec.client()
    with pytest.raises(GitHubUnavailable) as exc:
        await client.get_pull("stellar", "js-stellar-sdk", 1747)
    assert exc.value.retry_at is not None and int(exc.value.retry_at.timestamp()) == reset
    assert float(await fake_redis.get(BACKOFF_KEY)) == reset  # type: ignore[attr-defined]
    with pytest.raises(GitHubUnavailable):
        await client.get_pull("stellar", "js-stellar-sdk", 1744)
    assert len(rec.requests) == 1  # the second call never reached GitHub


async def test_cached_data_is_served_while_backing_off(fake_redis: object) -> None:
    rec = Recorder()
    client = rec.client()
    pr = await client.get_json("/repos/stellar/js-stellar-sdk/pulls/1747", shape=lambda b: b, fresh_seconds=0)
    await fake_redis.set(BACKOFF_KEY, str(time.time() + 300))  # type: ignore[attr-defined]
    stale = await client.get_json(
        "/repos/stellar/js-stellar-sdk/pulls/1747", shape=lambda b: b, fresh_seconds=0
    )
    assert stale == pr
    assert len(rec.requests) == 1


async def test_network_errors_become_unavailable(fake_redis: object) -> None:
    async def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(GitHubUnavailable, match="could not be reached"):
        await Recorder(broken).client().get_pull("stellar", "js-stellar-sdk", 1744)


async def test_gists_are_never_cached(fake_redis: object) -> None:
    rec = Recorder()
    client = rec.client()
    with pytest.raises(GitHubNotFound):
        await client.get_gist("feedfacecafe1234")
    await register_gist("feedfacecafe1234", owner_login="Ryang-21", owner_id=104600435, content="hello")
    gist = await client.get_gist("feedfacecafe1234")
    assert gist["owner"] == {
        "login": "Ryang-21",
        "id": 104600435,
        "avatar_url": "https://avatars.githubusercontent.com/u/104600435?v=4",
        "html_url": "https://github.com/Ryang-21",
        "type": "User",
    }
    assert json.dumps(gist["files"]).count("hello") == 1
    assert len(rec.requests) == 2


async def test_oauth_exchange_and_user(fake_redis: object) -> None:
    async def github(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            assert b"client_secret=shh" in request.content
            return httpx.Response(200, json={"access_token": "gho_once", "token_type": "bearer", "scope": ""})
        if request.url.path == "/user":
            assert request.headers["authorization"] == "Bearer gho_once"
            return await fixture_handler(httpx.Request("GET", "https://api.github.com/users/Ryang-21"))
        return httpx.Response(404, json={})

    client = Recorder(github).client(github_client_id="Iv1.test", github_client_secret="shh")
    token = await client.exchange_oauth_code("code-1", "http://localhost:5173/app/settings/github/callback")
    user = await client.get_authenticated_user(token)
    assert (user["login"], user["id"]) == ("Ryang-21", 104600435)
