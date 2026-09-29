"""Pull request verification rules (pure functions over GitHub API responses, no I/O).

A pull request is **verified** when it exists, is opened against the bounty's repository (when the bounty names
one), and was opened by the GitHub account the contributor proved they own. Its state (open, closed, merged)
and the combined checks of its head commit are recorded alongside, whatever the verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modules.github.models import ChecksStatus, PullRequestState, PullRequestVerification

_PASSED = frozenset({"success", "neutral", "skipped"})
_FAILED = frozenset({"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"})
_STATUS_FAILED = frozenset({"failure", "error"})
MAX_LISTED_CHECKS = 50


@dataclass(frozen=True)
class ChecksSummary:
    status: ChecksStatus
    passed: int = 0
    failed: int = 0
    pending: int = 0
    check_runs: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PullRequestFacts:
    verification: PullRequestVerification
    detail: str | None
    state: PullRequestState
    title: str | None
    author_login: str | None
    author_id: int | None
    base_repo: str | None
    base_repo_id: int | None
    merged_at: datetime | None
    head_sha: str | None
    html_url: str | None
    draft: bool
    head_ref: str | None
    base_ref: str | None


def pull_request_state(pr: Mapping[str, Any]) -> PullRequestState:
    if pr.get("merged") or pr.get("merged_at"):
        return PullRequestState.MERGED
    if pr.get("state") == "closed":
        return PullRequestState.CLOSED
    return PullRequestState.OPEN


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize_checks(
    check_runs: Mapping[str, Any] | None, combined: Mapping[str, Any] | None
) -> ChecksSummary:
    """Combines check runs (GitHub Actions and apps) and legacy commit statuses into one verdict: any failure
    fails, otherwise anything unfinished is pending, otherwise success. No checks at all is ``NONE``."""
    passed = failed = pending = 0
    runs: list[dict[str, Any]] = []
    for run in (check_runs or {}).get("check_runs") or []:
        status, conclusion = run.get("status"), run.get("conclusion")
        if status != "completed":
            pending += 1
        elif conclusion in _PASSED:
            passed += 1
        elif conclusion in _FAILED:
            failed += 1
        else:
            pending += 1
        if len(runs) < MAX_LISTED_CHECKS:
            runs.append({"name": run.get("name"), "status": status, "conclusion": conclusion})
    statuses: list[dict[str, Any]] = []
    # GitHub reports a combined state of "pending" when a commit has no statuses at all; only count real ones.
    if combined and int(combined.get("total_count") or 0) > 0:
        for s in combined.get("statuses") or []:
            state = s.get("state")
            if state == "success":
                passed += 1
            elif state in _STATUS_FAILED:
                failed += 1
            else:
                pending += 1
            if len(statuses) < MAX_LISTED_CHECKS:
                statuses.append({"context": s.get("context"), "state": state})
    if failed:
        verdict = ChecksStatus.FAILURE
    elif pending:
        verdict = ChecksStatus.PENDING
    elif passed:
        verdict = ChecksStatus.SUCCESS
    else:
        verdict = ChecksStatus.NONE
    return ChecksSummary(verdict, passed, failed, pending, runs, statuses)


def evaluate_pull_request(
    pr: Mapping[str, Any],
    *,
    expected_repo: tuple[str, str] | None,
    expected_repo_id: int | None = None,
    contributor_github_id: int | None,
    contributor_login: str | None = None,
) -> PullRequestFacts:
    """Verifies one pull request (a GitHub ``GET /repos/{owner}/{repo}/pulls/{number}`` body) against the
    bounty's repository and the contributor's verified GitHub account."""
    base = pr.get("base") or {}
    base_repo = base.get("repo") or {}
    user = pr.get("user") or {}
    head = pr.get("head") or {}
    full_name = base_repo.get("full_name")
    author_login = user.get("login")
    author_id = user.get("id")

    verification = PullRequestVerification.VERIFIED
    detail: str | None = None
    if expected_repo is not None:
        expected = f"{expected_repo[0]}/{expected_repo[1]}"
        same_name = isinstance(full_name, str) and full_name.lower() == expected
        # A renamed or transferred repository keeps its id; the bounty may still use the old URL.
        same_id = expected_repo_id is not None and base_repo.get("id") == expected_repo_id
        if not (same_name or same_id):
            verification = PullRequestVerification.REPO_MISMATCH
            detail = (
                f"Opened against {full_name or 'another repository'}, not the bounty's repository {expected}."
            )
    if verification == PullRequestVerification.VERIFIED:
        if contributor_github_id is None:
            verification = PullRequestVerification.AUTHOR_NOT_LINKED
            detail = "The contributor has not linked a verified GitHub account, so authorship is unconfirmed."
        elif author_id != contributor_github_id:
            verification = PullRequestVerification.AUTHOR_MISMATCH
            linked = f"@{contributor_login}" if contributor_login else "the contributor's verified account"
            detail = f"Opened by @{author_login}, not {linked}."

    return PullRequestFacts(
        verification=verification,
        detail=detail,
        state=pull_request_state(pr),
        title=(str(pr.get("title"))[:300] if pr.get("title") else None),
        author_login=str(author_login)[:39] if author_login else None,
        author_id=int(author_id) if isinstance(author_id, int) else None,
        base_repo=str(full_name)[:200] if full_name else None,
        base_repo_id=base_repo.get("id") if isinstance(base_repo.get("id"), int) else None,
        merged_at=_parse_time(pr.get("merged_at")),
        head_sha=str(head.get("sha"))[:40] if head.get("sha") else None,
        html_url=pr.get("html_url"),
        draft=bool(pr.get("draft")),
        head_ref=head.get("ref"),
        base_ref=base.get("ref"),
    )


def gist_proves_ownership(gist: Mapping[str, Any], *, login: str, challenge: str) -> str | None:
    """None when the gist is owned by ``login`` and one of its files contains ``challenge``; otherwise the
    reason it does not prove ownership."""
    owner = (gist.get("owner") or {}).get("login")
    if not owner:
        return "This gist has no owner (anonymous gists cannot prove an account)."
    if str(owner).lower() != login.lower():
        return f"This gist belongs to @{owner}, not @{login}."
    for f in (gist.get("files") or {}).values():
        if challenge in str((f or {}).get("content") or ""):
            return None
    return "The gist does not contain the verification text. Paste it exactly as shown, then try again."
