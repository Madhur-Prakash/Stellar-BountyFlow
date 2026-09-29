"""Pull request verification rules against recorded, real GitHub API responses (tests/fixtures/github)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.github import webhook
from app.modules.github.client import shape_check_runs, shape_gist, shape_pull, shape_status
from app.modules.github.models import (
    ChecksStatus,
    PullRequestState,
    PullRequestVerification,
    SubmissionPullRequest,
)
from app.modules.github.schemas import validate_pull_request_urls
from app.modules.github.service import merge_requirement_problem
from app.modules.github.urls import parse_gist_id, parse_pull_request_url, parse_repository_url
from app.modules.github.verification import evaluate_pull_request, gist_proves_ownership, summarize_checks
from tests.support.github_fixtures import AUTHOR_ID, AUTHOR_LOGIN, gist_body, load_body

SDK = ("stellar", "js-stellar-sdk")


def pull(repo: str, number: int) -> dict[str, Any]:
    return load_body(f"GET_repos_stellar_{repo}_pulls_{number}.json")


def checks_for(repo: str, pr: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    sha = pr["head"]["sha"]
    runs = load_body(f"GET_repos_stellar_{repo}_commits_{sha}_check-runs.json")
    status = load_body(f"GET_repos_stellar_{repo}_commits_{sha}_status.json")
    return runs, status


# --- URLs -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/stellar/js-stellar-sdk/pull/1744", ("stellar", "js-stellar-sdk", 1744)),
        ("https://github.com/Stellar/JS-Stellar-SDK/pull/1744/files", ("stellar", "js-stellar-sdk", 1744)),
        (
            "http://www.github.com/stellar/js-stellar-sdk/pull/7#issuecomment-1",
            ("stellar", "js-stellar-sdk", 7),
        ),
    ],
)
def test_pull_request_urls_are_parsed_and_lower_cased(url: str, expected: tuple[str, str, int]) -> None:
    ref = parse_pull_request_url(url)
    assert ref is not None
    assert (ref.owner, ref.repo, ref.number) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/stellar/js-stellar-sdk/issues/1744",
        "https://gitlab.com/stellar/js-stellar-sdk/pull/1744",
        "https://github.com.evil.example/stellar/js-stellar-sdk/pull/1",
        "https://user:pass@github.com/stellar/js-stellar-sdk/pull/1",
        "https://github.com/stellar/js-stellar-sdk/pull/abc",
        "https://github.com/-bad-/repo/pull/1",
        "javascript:alert(1)",
    ],
)
def test_non_pull_request_urls_are_rejected(url: str) -> None:
    assert parse_pull_request_url(url) is None


def test_pull_request_url_list_is_canonical_and_deduplicated() -> None:
    urls = validate_pull_request_urls(
        [
            "https://github.com/Stellar/js-stellar-sdk/pull/1744/files",
            "https://github.com/stellar/js-stellar-sdk/pull/1744",
            "https://github.com/stellar/js-stellar-base/pull/978",
        ]
    )
    assert urls == [
        "https://github.com/stellar/js-stellar-sdk/pull/1744",
        "https://github.com/stellar/js-stellar-base/pull/978",
    ]
    with pytest.raises(ValueError, match="GitHub pull request URL"):
        validate_pull_request_urls(["https://example.com/pull/1"])


def test_repository_and_gist_urls() -> None:
    assert parse_repository_url("https://github.com/stellar/js-stellar-sdk.git") == SDK
    assert parse_repository_url("https://github.com/Stellar/JS-Stellar-SDK/tree/master") == SDK
    assert parse_repository_url("https://gitlab.com/stellar/js-stellar-sdk") is None
    assert parse_repository_url(None) is None
    assert parse_gist_id("https://gist.github.com/octocat/6cad326836d38bd3a7ae") == "6cad326836d38bd3a7ae"
    assert parse_gist_id("https://gist.github.com/6cad326836d38bd3a7ae") == "6cad326836d38bd3a7ae"
    assert parse_gist_id("6CAD326836D38BD3A7AE") == "6cad326836d38bd3a7ae"
    assert parse_gist_id("https://github.com/octocat/6cad326836d38bd3a7ae") is None


# --- Verdicts on real pull requests -----------------------------------------------------------------------


def test_merged_pull_request_by_the_linked_author_is_verified() -> None:
    pr = shape_pull(pull("js-stellar-sdk", 1744))
    facts = evaluate_pull_request(
        pr, expected_repo=SDK, contributor_github_id=AUTHOR_ID, contributor_login=AUTHOR_LOGIN
    )
    assert facts.verification == PullRequestVerification.VERIFIED
    assert facts.detail is None
    assert facts.state == PullRequestState.MERGED
    assert facts.merged_at == datetime(2026, 9, 24, 22, 25, 15, tzinfo=UTC)
    assert facts.author_login == "Ryang-21"
    assert facts.base_repo == "stellar/js-stellar-sdk"
    assert facts.head_sha == "e472ff276862e95de544a704339f651447d99edb"
    assert facts.title and facts.title.startswith("fix(contract): forward wallet signerAddress")


def test_raw_and_shaped_responses_give_the_same_verdict() -> None:
    raw = pull("js-stellar-sdk", 1744)
    shaped = shape_pull(copy.deepcopy(raw))
    kwargs: dict[str, Any] = {"expected_repo": SDK, "contributor_github_id": AUTHOR_ID}
    assert evaluate_pull_request(raw, **kwargs) == evaluate_pull_request(shaped, **kwargs)


def test_open_pull_request_is_verified_but_open() -> None:
    facts = evaluate_pull_request(
        pull("js-stellar-sdk", 1747), expected_repo=SDK, contributor_github_id=AUTHOR_ID
    )
    assert facts.verification == PullRequestVerification.VERIFIED
    assert facts.state == PullRequestState.OPEN
    assert facts.merged_at is None


def test_pull_request_by_someone_else_is_an_author_mismatch() -> None:
    facts = evaluate_pull_request(
        pull("js-stellar-sdk", 1739),
        expected_repo=SDK,
        contributor_github_id=AUTHOR_ID,
        contributor_login=AUTHOR_LOGIN,
    )
    assert facts.verification == PullRequestVerification.AUTHOR_MISMATCH
    assert facts.detail == "Opened by @kanwalpreetd, not @Ryang-21."


def test_pull_request_without_a_linked_account_is_unconfirmed() -> None:
    facts = evaluate_pull_request(pull("js-stellar-sdk", 1744), expected_repo=SDK, contributor_github_id=None)
    assert facts.verification == PullRequestVerification.AUTHOR_NOT_LINKED


def test_pull_request_in_another_repository_is_a_repo_mismatch() -> None:
    facts = evaluate_pull_request(
        pull("js-stellar-base", 978), expected_repo=SDK, contributor_github_id=AUTHOR_ID
    )
    assert facts.verification == PullRequestVerification.REPO_MISMATCH
    assert facts.detail == (
        "Opened against stellar/js-stellar-base, not the bounty's repository stellar/js-stellar-sdk."
    )
    # Without a repository on the bounty any repository is fine.
    assert (
        evaluate_pull_request(
            pull("js-stellar-base", 978), expected_repo=None, contributor_github_id=AUTHOR_ID
        ).verification
        == PullRequestVerification.VERIFIED
    )


def test_renamed_repository_matches_by_id() -> None:
    pr = pull("js-stellar-sdk", 1744)
    facts = evaluate_pull_request(
        pr,
        expected_repo=("stellar", "old-sdk-name"),
        expected_repo_id=33684726,
        contributor_github_id=AUTHOR_ID,
    )
    assert facts.verification == PullRequestVerification.VERIFIED


def test_closed_without_merge() -> None:
    facts = evaluate_pull_request(
        pull("js-stellar-sdk", 1716), expected_repo=SDK, contributor_github_id=63041352
    )
    assert facts.state == PullRequestState.CLOSED
    assert facts.verification == PullRequestVerification.VERIFIED


# --- Checks -----------------------------------------------------------------------------------------------


def test_recorded_checks_pass_and_an_empty_combined_status_is_ignored() -> None:
    pr = pull("js-stellar-sdk", 1744)
    runs, status = checks_for("js-stellar-sdk", pr)
    assert status["state"] == "pending" and status["total_count"] == 0  # GitHub's answer for "no statuses"
    summary = summarize_checks(shape_check_runs(runs), shape_status(status))
    assert summary.status == ChecksStatus.SUCCESS
    assert summary.passed == runs["total_count"] == 18
    assert summary.failed == summary.pending == 0
    assert all(r["conclusion"] == "success" for r in summary.check_runs)


def test_any_failure_fails_and_unfinished_checks_are_pending() -> None:
    runs, status = checks_for("js-stellar-sdk", pull("js-stellar-sdk", 1747))
    failing = copy.deepcopy(runs)
    failing["check_runs"][0]["conclusion"] = "failure"
    failing["check_runs"][1].update(status="in_progress", conclusion=None)
    summary = summarize_checks(failing, status)
    assert summary.status == ChecksStatus.FAILURE
    assert (summary.failed, summary.pending) == (1, 1)

    running = copy.deepcopy(runs)
    running["check_runs"][1].update(status="queued", conclusion=None)
    assert summarize_checks(running, status).status == ChecksStatus.PENDING

    with_status = copy.deepcopy(status)
    with_status.update(total_count=1, statuses=[{"context": "ci/legacy", "state": "error"}])
    assert summarize_checks(runs, with_status).status == ChecksStatus.FAILURE
    assert summarize_checks(None, None).status == ChecksStatus.NONE


# --- Gist proof ------------------------------------------------------------------------------------------


def test_gist_proves_ownership_only_for_its_owner_and_the_exact_challenge() -> None:
    challenge = "bountyflow:kai-tanaka:0123456789abcdef0123456789abcdef"
    gist = shape_gist(
        gist_body("abc123def456", owner_login="Ryang-21", owner_id=AUTHOR_ID, content=challenge)
    )
    assert gist_proves_ownership(gist, login="ryang-21", challenge=challenge) is None
    assert gist_proves_ownership(gist, login="octocat", challenge=challenge) == (
        "This gist belongs to @Ryang-21, not @octocat."
    )
    assert "does not contain" in (
        gist_proves_ownership(gist, login="Ryang-21", challenge=challenge + "0") or ""
    )
    # The recorded real gist (octocat's hello world) proves nothing.
    real = shape_gist(load_body("GET_gists_6cad326836d38bd3a7ae.json"))
    assert real["owner"]["login"] == "octocat"
    assert "does not contain" in (gist_proves_ownership(real, login="octocat", challenge=challenge) or "")


# --- Webhook ---------------------------------------------------------------------------------------------


def test_webhook_signature_is_hmac_sha256_and_constant_time_checked() -> None:
    body = b'{"action":"closed"}'
    header = webhook.signature("s3cret", body)
    assert header.startswith("sha256=") and len(header) == 71
    assert webhook.verify_signature("s3cret", body, header)
    assert not webhook.verify_signature("s3cret", body + b" ", header)
    assert not webhook.verify_signature("other", body, header)
    assert not webhook.verify_signature("s3cret", body, None)
    assert not webhook.verify_signature("s3cret", body, header.replace("sha256=", "sha1="))


def test_webhook_targets() -> None:
    pr = pull("js-stellar-sdk", 1744)
    found = webhook.targets(
        "pull_request",
        {"action": "closed", "number": 1744, "pull_request": pr, "repository": pr["base"]["repo"]},
    )
    assert found == {
        "owner": "stellar",
        "repo": "js-stellar-sdk",
        "number": 1744,
        "head_sha": pr["head"]["sha"],
    }
    assert webhook.targets("check_run", {"check_run": {"head_sha": "abc"}}) == {"head_sha": "abc"}
    assert webhook.targets("status", {"sha": "def"}) == {"head_sha": "def"}
    assert webhook.targets("issues", {}) == {}


# --- Approval gate ----------------------------------------------------------------------------------------


def row(**kw: Any) -> SubmissionPullRequest:
    base: dict[str, Any] = {
        "repo_owner": "stellar",
        "repo_name": "js-stellar-sdk",
        "number": 1744,
        "base_repo": "stellar/js-stellar-sdk",
        "verification": PullRequestVerification.VERIFIED,
        "state": PullRequestState.MERGED,
        "author_id": AUTHOR_ID,
        "author_login": AUTHOR_LOGIN,
        "snapshot": {},
    }
    base.update(kw)
    return SubmissionPullRequest(**base)


BOUNTY = SimpleNamespace(require_merged_pr=True, repository_url="https://github.com/stellar/js-stellar-sdk")
ACCOUNT = SimpleNamespace(github_id=AUTHOR_ID, login=AUTHOR_LOGIN)


def test_merge_requirement_passes_with_a_verified_merged_pull_request() -> None:
    assert merge_requirement_problem(BOUNTY, [row()], ACCOUNT) is None  # type: ignore[arg-type]
    assert (
        merge_requirement_problem(  # not required: always fine
            SimpleNamespace(require_merged_pr=False, repository_url=None),
            [],
            None,  # type: ignore[arg-type]
        )
        is None
    )


@pytest.mark.parametrize(
    ("rows", "account", "message"),
    [
        ([], ACCOUNT, "this submission links none."),
        (
            [row(number=1747, state=PullRequestState.OPEN)],
            ACCOUNT,
            "stellar/js-stellar-sdk#1747 is still open.",
        ),
        ([row(number=1716, state=PullRequestState.CLOSED)], ACCOUNT, "was closed without being merged."),
        (
            [
                row(
                    number=1739,
                    verification=PullRequestVerification.AUTHOR_MISMATCH,
                    author_id=5859175,
                    author_login="kanwalpreetd",
                )
            ],
            ACCOUNT,
            "stellar/js-stellar-sdk#1739 was opened by @kanwalpreetd, not the contributor's verified account @Ryang-21.",
        ),
        (
            [row(verification=PullRequestVerification.AUTHOR_NOT_LINKED)],
            None,
            "has not linked a GitHub account",
        ),
        (
            [
                row(
                    repo_name="js-stellar-base",
                    number=978,
                    base_repo="stellar/js-stellar-base",
                    verification=PullRequestVerification.REPO_MISMATCH,
                )
            ],
            ACCOUNT,
            "stellar/js-stellar-base#978 is in stellar/js-stellar-base, not stellar/js-stellar-sdk.",
        ),
        (
            [row(number=999999, verification=PullRequestVerification.NOT_FOUND, base_repo=None)],
            ACCOUNT,
            "was not found on GitHub.",
        ),
        (
            [row(verification=PullRequestVerification.UNAVAILABLE, state=None)],
            ACCOUNT,
            "GitHub could not be reached",
        ),
        # The account changed after verification: the merged pull request no longer belongs to the contributor.
        (
            [row()],
            SimpleNamespace(github_id=1, login="someone-else"),
            "not the contributor's verified account @someone-else.",
        ),
    ],
)
def test_merge_requirement_explains_precisely_why_approval_is_blocked(
    rows: list[SubmissionPullRequest], account: Any, message: str
) -> None:
    problem = merge_requirement_problem(BOUNTY, rows, account)  # type: ignore[arg-type]
    assert problem is not None
    assert problem.startswith("This bounty requires a merged pull request from the contributor")
    assert message in problem
