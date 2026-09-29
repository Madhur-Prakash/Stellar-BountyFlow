"""Replays recorded, real GitHub REST API responses (``tests/fixtures/github``) through an ``httpx.MockTransport``.

The fixtures were captured from public pull requests in ``stellar/js-stellar-sdk`` and ``stellar/js-stellar-base``
(a merged PR, an open PR by the same author, an open PR from a fork by someone else, a PR closed without merging,
a merged PR in another repository, and a 404), their head commits' check runs and statuses, the repository, a
public gist and a user. Unknown paths answer GitHub's real 404 body. ETags are honoured (``If-None-Match`` -> 304).

Gists that prove account ownership are never recorded from a real person: tests register one with
``register_gist``, which builds a response from the recorded gist's shape with the owner and content they need.
Registered gists live in Redis (``bf:v1:github:fixture-gist:{id}``), so the Playwright suite can register one for
the API it drives. Only used when ``GITHUB_FIXTURE_TRANSPORT`` is on (development/test) or injected by tests.
"""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from app.cache import keys
from app.cache.redis import get_redis

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "github"
GIST_TEMPLATE = "GET_gists_6cad326836d38bd3a7ae.json"
USER_TEMPLATE = "GET_users_Ryang-21.json"
NOT_FOUND = {"message": "Not Found", "documentation_url": "https://docs.github.com/rest", "status": "404"}

# The recorded pull requests, for tests.
REPO = "https://github.com/stellar/js-stellar-sdk"
MERGED_PR = f"{REPO}/pull/1744"  # merged, by Ryang-21 (id 104600435)
OPEN_PR = f"{REPO}/pull/1747"  # open, by Ryang-21
FORK_PR = f"{REPO}/pull/1739"  # open, from a fork, by kanwalpreetd
CLOSED_PR = f"{REPO}/pull/1716"  # closed without merging, by jaredrainsha
OTHER_REPO_PR = "https://github.com/stellar/js-stellar-base/pull/978"  # merged, by Ryang-21
MISSING_PR = f"{REPO}/pull/999999"  # 404
AUTHOR_LOGIN = "Ryang-21"
AUTHOR_ID = 104600435


def fixture_name(method: str, path: str) -> str:
    return method.upper() + "_" + re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/")) + ".json"


@lru_cache(maxsize=64)
def _load(name: str) -> dict[str, Any] | None:
    path = FIXTURE_DIR / name
    if not path.exists():
        return None
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return record


def load_body(name: str) -> Any:
    record = _load(name)
    assert record is not None, f"missing fixture {name}"
    return copy.deepcopy(record["body"])


def _gist_key(gist_id: str) -> str:
    return f"{keys.PREFIX}:github:fixture-gist:{gist_id.lower()}"


def gist_body(gist_id: str, *, owner_login: str, owner_id: int, content: str) -> dict[str, Any]:
    """A gist response in GitHub's recorded shape, owned by ``owner_login`` with one file holding ``content``."""
    body = load_body(GIST_TEMPLATE)
    user = load_body(USER_TEMPLATE)
    user.update(
        login=owner_login,
        id=owner_id,
        html_url=f"https://github.com/{owner_login}",
        avatar_url=f"https://avatars.githubusercontent.com/u/{owner_id}?v=4",
    )
    body.update(
        id=gist_id,
        url=f"https://api.github.com/gists/{gist_id}",
        html_url=f"https://gist.github.com/{owner_login}/{gist_id}",
        owner=user,
        history=[],
        forks=[],
        description="BountyFlow verification",
    )
    body["files"] = {
        "bountyflow-verification.txt": {
            "filename": "bountyflow-verification.txt",
            "type": "text/plain",
            "language": "Text",
            "raw_url": f"https://gist.githubusercontent.com/{owner_login}/{gist_id}/raw/bountyflow-verification.txt",
            "size": len(content),
            "truncated": False,
            "content": content,
        }
    }
    return body


async def register_gist(gist_id: str, *, owner_login: str, owner_id: int, content: str) -> None:
    await get_redis().set(
        _gist_key(gist_id),
        json.dumps({"owner_login": owner_login, "owner_id": owner_id, "content": content}),
        ex=3600,
    )


async def _registered_gist(gist_id: str) -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(_gist_key(gist_id))
    except Exception:
        return None
    if not raw:
        return None
    data = json.loads(raw)
    return gist_body(
        gist_id,
        owner_login=str(data["owner_login"]),
        owner_id=int(data["owner_id"]),
        content=str(data["content"]),
    )


def _json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    base = {
        "content-type": "application/json; charset=utf-8",
        "x-ratelimit-remaining": "59",
        "x-ratelimit-limit": "60",
    }
    base.update({k: v for k, v in (headers or {}).items() if k != "content-type"})
    return httpx.Response(status, headers=base, content=json.dumps(body).encode())


async def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.method == "GET" and path.startswith("/gists/"):
        gist = await _registered_gist(path.rsplit("/", 1)[-1])
        if gist is not None:
            return _json_response(200, gist)
    record = _load(fixture_name(request.method, path))
    if record is None:
        return _json_response(404, NOT_FOUND)
    headers = dict(record.get("headers") or {})
    etag = headers.get("etag")
    if etag and request.headers.get("if-none-match") == etag:
        return httpx.Response(304, headers={k: v for k, v in headers.items() if k != "content-type"})
    return _json_response(int(record["status"]), copy.deepcopy(record["body"]), headers)


def fixture_transport() -> httpx.AsyncBaseTransport:
    return httpx.MockTransport(handler)
