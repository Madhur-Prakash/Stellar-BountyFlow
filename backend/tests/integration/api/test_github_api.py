"""GitHub end to end through the API, with GitHub itself replaced by recorded real responses (injected transport):
gist account linking, pull requests on submissions and their verification, the merged-PR approval gate, on-demand
and scheduled re-checks, and the HMAC-verified webhook."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import utcnow
from app.modules.github import transport
from app.modules.github.models import SubmissionPullRequest
from app.modules.github.webhook import signature
from app.modules.notifications.models import Notification, NotificationType
from app.modules.submissions.models import BountySubmission, OnchainReviewState
from tests.integration.api.conftest import ApiClient, drain_events
from tests.integration.security.helpers import assigned_contributor, funded, new_requester
from tests.support.github_fixtures import (
    AUTHOR_ID,
    AUTHOR_LOGIN,
    CLOSED_PR,
    FORK_PR,
    MERGED_PR,
    MISSING_PR,
    OPEN_PR,
    OTHER_REPO_PR,
    REPO,
    fixture_transport,
    handler,
    register_gist,
)
from worker.jobs.github_prs import run_recheck_once


class CountingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.inner = fixture_transport()
        self.paths: list[str] = []
        self.override: dict[str, Any] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if request.url.path in self.override:
            return httpx.Response(200, json=self.override[request.url.path])
        return await self.inner.handle_async_request(request)


@pytest.fixture
def github() -> Iterator[CountingTransport]:
    t = CountingTransport()
    transport.set_transport(t)
    try:
        yield t
    finally:
        transport.set_transport(None)


async def link_github(
    client: ApiClient, login: str = AUTHOR_LOGIN, github_id: int = AUTHOR_ID, gist: str = "a1b2c3d4e5f6"
) -> dict[str, Any]:
    challenge = await client.post("/github/account/challenge", {"login": login})
    await register_gist(
        gist,
        owner_login=login,
        owner_id=github_id,
        content=f"My BountyFlow proof\n{challenge['challenge']}\n",
    )
    return await client.post(
        "/github/account/verify-gist", {"gist_url": f"https://gist.github.com/{login}/{gist}"}
    )


async def test_gist_linking_proves_ownership(
    client_factory: Any, outbox_mail: Any, github: CountingTransport
) -> None:
    user, _ = await new_requester(client_factory, outbox_mail, "gh_link")
    assert await user.get("/github/account") is None
    await user.request(
        "POST",
        "/github/account/verify-gist",
        json={"gist_url": "https://gist.github.com/x/abcdef12"},
        expected=422,
    )

    challenge = await user.post("/github/account/challenge", {"login": "@Ryang-21"})
    assert challenge["login"] == "Ryang-21"
    assert challenge["challenge"].startswith(f"bountyflow:{user.me['username']}:")  # type: ignore[index]
    # A gist owned by someone else, or without the text, proves nothing.
    await register_gist("0badc0de01", owner_login="octocat", owner_id=583231, content=challenge["challenge"])
    wrong_owner = await user.request(
        "POST", "/github/account/verify-gist", json={"gist_url": "https://gist.github.com/octocat/0badc0de01"}
    )
    assert wrong_owner.status_code == 422
    assert wrong_owner.json()["error"]["message"] == "This gist belongs to @octocat, not @Ryang-21."
    await register_gist(
        "0badc0de02", owner_login="Ryang-21", owner_id=AUTHOR_ID, content="bountyflow:someone:else"
    )
    missing_text = await user.request("POST", "/github/account/verify-gist", json={"gist_url": "0badc0de02"})
    assert missing_text.json()["error"]["code"] == "gist_not_verified"
    not_found = await user.request(
        "POST", "/github/account/verify-gist", json={"gist_url": "https://gist.github.com/deadbeef99"}
    )
    assert not_found.json()["error"]["code"] == "gist_not_found"

    await register_gist(
        "0badc0de03", owner_login="Ryang-21", owner_id=AUTHOR_ID, content=challenge["challenge"]
    )
    account = await user.post(
        "/github/account/verify-gist", {"gist_url": "https://gist.github.com/Ryang-21/0badc0de03"}
    )
    assert (
        account["login"] == "Ryang-21" and account["github_id"] == AUTHOR_ID and account["method"] == "GIST"
    )
    assert account["proof_url"] == "https://gist.github.com/Ryang-21/0badc0de03"
    assert (await client_factory().get(f"/users/{user.me['username']}/github"))["login"] == "Ryang-21"  # type: ignore[index]
    # The challenge is single use.
    replay = await user.request("POST", "/github/account/verify-gist", json={"gist_url": "0badc0de03"})
    assert replay.json()["error"]["code"] == "challenge_expired"

    # One BountyFlow account per GitHub account.
    other, _ = await new_requester(client_factory, outbox_mail, "gh_other")
    taken = await other.request("POST", "/github/account/verify-gist", json={"gist_url": "x"})
    assert taken.status_code == 422
    challenge = await other.post("/github/account/challenge", {"login": "Ryang-21"})
    await register_gist(
        "0badc0de04", owner_login="Ryang-21", owner_id=AUTHOR_ID, content=challenge["challenge"]
    )
    conflict = await other.request("POST", "/github/account/verify-gist", json={"gist_url": "0badc0de04"})
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "github_account_taken"

    await user.request("DELETE", "/github/account", expected=204)
    assert await user.get("/github/account") is None
    assert await client_factory().get(f"/users/{user.me['username']}/github") is None  # type: ignore[index]
    assert all(p.startswith("/gists/") for p in github.paths)


async def test_oauth_is_off_without_client_credentials(client_factory: Any, outbox_mail: Any) -> None:
    user, _ = await new_requester(client_factory, outbox_mail, "gh_oauth")
    config = await client_factory().get("/github/config")
    assert config == {"oauth_enabled": False, "webhook_enabled": False, "authenticated_api": False}
    response = await user.request("POST", "/github/oauth/start")
    assert response.status_code == 400 and response.json()["error"]["code"] == "github_oauth_disabled"


async def _submission_with_prs(
    client_factory: Any, mail: Any, urls: list[str], **bounty: Any
) -> tuple[ApiClient, ApiClient, dict[str, Any], dict[str, Any]]:
    requester, wallet = await new_requester(client_factory, mail, "gh_req")
    funded_bounty = await funded(requester, wallet, repository_url=REPO, require_merged_pr=True, **bounty)
    contributor, _, _ = await assigned_contributor(client_factory, requester, funded_bounty["id"], "gh_dev")
    await link_github(contributor)
    submission = await contributor.post(
        f"/bounties/{funded_bounty['id']}/submissions",
        {"description": "Implemented the widget; see the linked pull requests.", "pull_request_urls": urls},
        expected=201,
    )
    return requester, contributor, funded_bounty, submission


def by_number(submission: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {pr["number"]: pr for pr in submission["pull_requests"]}


async def test_submission_pull_requests_are_verified_and_gate_approval(
    client_factory: Any, outbox_mail: Any, github: CountingTransport, db_session: AsyncSession
) -> None:
    requester, contributor, bounty, submission = await _submission_with_prs(
        client_factory, outbox_mail, [OPEN_PR, FORK_PR, OTHER_REPO_PR, MISSING_PR, f"{REPO}/pull/1747/files"]
    )
    assert bounty["require_merged_pr"] is True
    prs = by_number(submission)
    assert sorted(prs) == [978, 1739, 1747, 999999]  # the duplicate URL collapsed
    assert prs[1747]["verification"] == "VERIFIED" and prs[1747]["state"] == "OPEN"
    assert prs[1747]["checks"] == "SUCCESS" and prs[1747]["checks_passed"] == 17
    assert prs[1747]["author_login"] == "Ryang-21" and prs[1747]["repository"] == "stellar/js-stellar-sdk"
    assert (
        prs[1739]["verification"] == "AUTHOR_MISMATCH"
        and prs[1739]["detail"] == "Opened by @kanwalpreetd, not @Ryang-21."
    )
    assert prs[978]["verification"] == "REPO_MISMATCH" and prs[978]["state"] == "MERGED"
    assert prs[999999]["verification"] == "NOT_FOUND" and prs[999999]["state"] is None
    assert prs[1747]["next_check_at"] is not None  # open: re-checked on a schedule
    assert prs[978]["next_check_at"] is None  # merged: no more checks

    # The requester sees the same cards.
    listed = await requester.get(f"/bounties/{bounty['id']}/submissions")
    assert sorted(by_number(listed["items"][0])) == [978, 1739, 1747, 999999]

    blocked = await requester.request("POST", f"/submissions/{submission['id']}/approve", json={})
    assert blocked.status_code == 409
    error = blocked.json()["error"]
    assert error["code"] == "merged_pr_required"
    assert error["message"].startswith("This bounty requires a merged pull request from the contributor.")
    assert "stellar/js-stellar-sdk#1747 is still open." in error["message"]

    # The contributor adds the merged pull request; now approval goes through.
    added = await contributor.post(
        f"/submissions/{submission['id']}/pull-requests", {"url": MERGED_PR}, expected=201
    )
    assert added["verification"] == "VERIFIED" and added["state"] == "MERGED"
    assert added["merged_at"].startswith("2026-09-24T22:25:15")
    await contributor.request(
        "POST", f"/submissions/{submission['id']}/pull-requests", json={"url": MERGED_PR}, expected=409
    )
    await requester.request(
        "POST", f"/submissions/{submission['id']}/pull-requests", json={"url": CLOSED_PR}, expected=404
    )
    approved = await requester.post(f"/submissions/{submission['id']}/approve", {})
    assert approved["status"] == "APPROVED"
    # Approved: nothing left to re-check, and links can no longer change.
    await contributor.request(
        "DELETE", f"/submissions/{submission['id']}/pull-requests/{added['id']}", expected=409
    )
    await run_recheck_once()
    due = (await db_session.scalars(select(SubmissionPullRequest.next_check_at))).all()
    assert all(d is None for d in due)


async def test_unlinked_author_and_rechecks(
    client_factory: Any, outbox_mail: Any, github: CountingTransport, db_session: AsyncSession
) -> None:
    requester, contributor, _bounty, submission = await _submission_with_prs(
        client_factory, outbox_mail, [OPEN_PR]
    )
    pr = submission["pull_requests"][0]

    # Unlinking re-derives authorship from the stored author id, without calling GitHub.
    calls = len(github.paths)
    await contributor.request("DELETE", "/github/account", expected=204)
    [unlinked] = await contributor.get(f"/submissions/{submission['id']}/pull-requests")
    assert unlinked["verification"] == "AUTHOR_NOT_LINKED" and len(github.paths) == calls
    blocked = await requester.request("POST", f"/submissions/{submission['id']}/approve", json={})
    assert "has not linked a GitHub account" in blocked.json()["error"]["message"]
    await link_github(contributor, gist="c0ffee0001")
    [relinked] = await requester.get(f"/submissions/{submission['id']}/pull-requests")
    assert relinked["verification"] == "VERIFIED"

    # On-demand re-check has a short cooldown; outsiders cannot see or trigger it.
    outsider, _ = await new_requester(client_factory, outbox_mail, "gh_outsider")
    await outsider.request("POST", f"/submissions/{submission['id']}/pull-requests/recheck", expected=404)
    calls = len(github.paths)
    await contributor.post(f"/submissions/{submission['id']}/pull-requests/recheck")
    assert len(github.paths) == calls  # checked moments ago: served from the snapshot

    # The PR is merged upstream: the scheduled job picks it up once due, stops re-checking, and notifies.
    merged = json.loads(
        (
            await handler(
                httpx.Request("GET", "https://api.github.com/repos/stellar/js-stellar-sdk/pulls/1744")
            )
        ).content
    )
    merged["number"] = 1747
    github.override["/repos/stellar/js-stellar-sdk/pulls/1747"] = merged
    await db_session.execute(
        update(SubmissionPullRequest)
        .where(SubmissionPullRequest.id == pr["id"])
        .values(
            next_check_at=utcnow() - timedelta(seconds=1), last_checked_at=utcnow() - timedelta(minutes=5)
        )
    )
    await db_session.commit()
    from app.cache.redis import get_redis

    await get_redis().flushdb()  # drop cached GitHub responses so the change is seen
    result = await run_recheck_once()
    assert result["checked"] == 1
    [after] = await requester.get(f"/submissions/{submission['id']}/pull-requests")
    assert after["state"] == "MERGED" and after["next_check_at"] is None
    await drain_events()
    titles = (
        await db_session.scalars(
            select(Notification.title).where(
                Notification.notification_type == NotificationType.PULL_REQUEST_UPDATE
            )
        )
    ).all()
    assert sorted(titles) == ["Pull request merged", "Pull request merged"]
    approved = await requester.post(f"/submissions/{submission['id']}/approve", {})
    assert approved["status"] == "APPROVED"


async def test_merged_pr_requirement_needs_a_github_repository(client_factory: Any, outbox_mail: Any) -> None:
    requester, _ = await new_requester(client_factory, outbox_mail, "gh_repo_rule")
    response = await requester.request(
        "POST",
        "/bounties",
        json={
            "title": "Bounty on a GitLab repository",
            "short_description": "A bounty whose code does not live on GitHub at all.",
            "description": "The description of this bounty is long enough to be accepted by validation.",
            "category": "DEVELOPMENT",
            "difficulty": "BEGINNER",
            "reward_amount": "5",
            "repository_url": "https://gitlab.com/org/repo",
            "require_merged_pr": True,
        },
    )
    assert response.status_code == 422
    assert "only be required when the repository is on GitHub" in response.json()["error"]["message"]


async def test_webhook_is_hmac_verified_and_schedules_rechecks(
    client_factory: Any,
    outbox_mail: Any,
    github: CountingTransport,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anon = client_factory()
    off = await anon.request("POST", "/github/webhook", content=b"{}", headers={"X-GitHub-Event": "ping"})
    assert off.status_code == 404  # off without a secret

    _, _, _, submission = await _submission_with_prs(client_factory, outbox_mail, [OPEN_PR])
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "whsec-test-only")
    get_settings.cache_clear()
    body = json.dumps(
        {
            "action": "synchronize",
            "number": 1747,
            "pull_request": {"number": 1747, "head": {"sha": "abc"}},
            "repository": {"full_name": "Stellar/JS-Stellar-SDK"},
        }
    ).encode()

    def headers(sig: str, delivery: str) -> dict[str, str]:
        return {
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": sig,
            "X-GitHub-Delivery": delivery,
            "Content-Type": "application/json",
        }

    bad = await anon.request(
        "POST", "/github/webhook", content=body, headers=headers("sha256=" + "0" * 64, "d-1")
    )
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "invalid_signature"
    good = await anon.request(
        "POST", "/github/webhook", content=body, headers=headers(signature("whsec-test-only", body), "d-2")
    )
    assert good.status_code == 202 and good.json() == {"ok": True, "rechecks": 1}
    replay = await anon.request(
        "POST", "/github/webhook", content=body, headers=headers(signature("whsec-test-only", body), "d-2")
    )
    assert replay.json()["duplicate"] is True
    [row] = (
        await db_session.scalars(
            select(SubmissionPullRequest).where(SubmissionPullRequest.submission_id == submission["id"])
        )
    ).all()
    await db_session.refresh(row)
    assert row.next_check_at is not None and row.next_check_at <= utcnow()
    assert (await anon.get("/github/config"))["webhook_enabled"] is True
    get_settings.cache_clear()


async def test_unmet_requirement_never_silences_the_onchain_review_clock(
    client_factory: Any, outbox_mail: Any, github: CountingTransport, db_session: AsyncSession
) -> None:
    """The escrow's review clock is the contract's, so an unmet pull request requirement is a reason to answer,
    not a reason to stay silent: approval is refused with a message that says the clock is still running, and
    requesting changes or rejecting stays available (on-chain while the clock runs)."""
    requester, _contributor, _bounty, submission = await _submission_with_prs(
        client_factory, outbox_mail, [OPEN_PR]
    )
    claimable_at = utcnow() + timedelta(days=6)
    await db_session.execute(
        update(BountySubmission)
        .where(BountySubmission.id == uuid.UUID(submission["id"]))
        .values(
            onchain_state=OnchainReviewState.PENDING,
            onchain_submitted_at=utcnow() - timedelta(days=1),
            claimable_at=claimable_at,
        )
    )
    await db_session.commit()

    blocked = await requester.request("POST", f"/submissions/{submission['id']}/approve", json={})
    assert blocked.status_code == 409
    error = blocked.json()["error"]
    assert error["code"] == "merged_pr_required"
    assert "stellar/js-stellar-sdk#1747 is still open." in error["message"]
    assert "review clock is still running" in error["message"]
    assert "staying silent does not hold the reward" in error["message"]
    assert "Request changes or reject on-chain" in error["message"]
    assert error["details"]["onchain_review_pending"] is True
    assert error["details"]["claimable_at"].startswith(claimable_at.strftime("%Y-%m-%d"))

    # Answering is never gated by the requirement: the escrow rule takes over and asks for the on-chain answer.
    answer = await requester.request(
        "POST", f"/submissions/{submission['id']}/request-revision", json={"feedback": "Merge the PR first."}
    )
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "onchain_review_pending"

    # Without a running clock the same block carries no clock warning.
    await db_session.execute(
        update(BountySubmission)
        .where(BountySubmission.id == uuid.UUID(submission["id"]))
        .values(onchain_state=None, claimable_at=None)
    )
    await db_session.commit()
    plain = await requester.request("POST", f"/submissions/{submission['id']}/approve", json={})
    assert plain.status_code == 409 and "review clock" not in plain.json()["error"]["message"]
    offchain = await requester.post(
        f"/submissions/{submission['id']}/request-revision", {"feedback": "Merge the PR first, please."}
    )
    assert offchain["status"] == "REVISION_REQUESTED"
