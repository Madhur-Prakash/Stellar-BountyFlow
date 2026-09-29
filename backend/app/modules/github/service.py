"""Pull requests linked to submissions: verification through the GitHub REST API, scheduled and on-demand
re-checks, webhook-triggered re-checks, and the "merged pull request required" approval gate.

**A check never holds a database transaction across the network.** It runs in three phases, like the chain
verification pipeline: read what the check needs in one joined query and end the read transaction; call GitHub;
then, in a single new transaction, lock the pull request rows (``SELECT … FOR UPDATE``, ordered by id), write
the snapshots, stage the events and commit once. Re-running a check is therefore safe: the row's stored state
inside the lock decides whether anything changed, so a redelivery or a second worker stages no duplicate event.
A GitHub outage leaves the last snapshot in place, marked with why it could not be refreshed.

Approval gate: on a bounty with ``require_merged_pr`` the requester can only approve once a merged pull request
opened by the contributor's verified GitHub account is verified. It never blocks *answering* — see
``review_clock_note`` for why that matters when the escrow's on-chain review clock is running.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.exceptions import Conflict, InvalidStateTransition, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.rate_limit import hit
from app.core.rbac import Permission, has_permission
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.bounties.models import Bounty
from app.modules.github.client import GitHubClient, GitHubNotFound, GitHubUnavailable
from app.modules.github.models import (
    GitHubAccount,
    PullRequestState,
    PullRequestVerification,
    SubmissionPullRequest,
)
from app.modules.github.schemas import MAX_PULL_REQUESTS, CheckRunOut, CommitStatusOut, PullRequestOut
from app.modules.github.urls import PullRequestRef, parse_pull_request_url, parse_repository_url
from app.modules.github.verification import (
    ChecksSummary,
    PullRequestFacts,
    evaluate_pull_request,
    summarize_checks,
)
from app.modules.submissions.models import BountySubmission, OnchainReviewState, SubmissionStatus
from app.modules.users.models import User

logger = get_logger(__name__)

# Submissions whose pull requests are still worth re-checking.
ACTIVE_SUBMISSIONS = (
    SubmissionStatus.SUBMITTED,
    SubmissionStatus.RESUBMITTED,
    SubmissionStatus.REVISION_REQUESTED,
)
EDITABLE_SUBMISSIONS = ACTIVE_SUBMISSIONS
TERMINAL_STATES = (PullRequestState.MERGED, PullRequestState.CLOSED)

RECHECK_AUTHENTICATED = timedelta(minutes=5)
RECHECK_UNAUTHENTICATED = timedelta(minutes=20)
RECHECK_NOT_FOUND = timedelta(hours=6)
FAILURE_BACKOFF = timedelta(minutes=2)
MAX_BACKOFF = timedelta(hours=6)
MANUAL_COOLDOWN = timedelta(seconds=20)


# --- Serialization -----------------------------------------------------------------------------


def serialize(row: SubmissionPullRequest) -> PullRequestOut:
    snap = row.snapshot or {}
    return PullRequestOut(
        id=row.id,
        url=row.url,
        repository=row.repository,
        number=row.number,
        verification=row.verification,
        detail=row.detail,
        state=row.state,
        title=row.title,
        author_login=row.author_login,
        merged_at=row.merged_at,
        head_sha=row.head_sha,
        draft=bool(snap.get("draft")),
        checks=row.checks,
        checks_passed=row.checks_passed,
        checks_failed=row.checks_failed,
        checks_pending=row.checks_pending,
        check_runs=[CheckRunOut.model_validate(c) for c in snap.get("check_runs") or []],
        statuses=[CommitStatusOut.model_validate(s) for s in snap.get("statuses") or []],
        last_checked_at=row.last_checked_at,
        next_check_at=row.next_check_at,
    )


async def for_submissions(
    session: AsyncSession, submission_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[SubmissionPullRequest]]:
    """Every submission's pull requests in one query (never one query per submission)."""
    if not submission_ids:
        return {}
    rows = await session.scalars(
        select(SubmissionPullRequest)
        .where(SubmissionPullRequest.submission_id.in_(submission_ids))
        .order_by(SubmissionPullRequest.position, SubmissionPullRequest.created_at)
    )
    grouped: dict[uuid.UUID, list[SubmissionPullRequest]] = {}
    for row in rows.all():
        grouped.setdefault(row.submission_id, []).append(row)
    return grouped


async def serialized_for_submissions(
    session: AsyncSession, submission_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[PullRequestOut]]:
    grouped = await for_submissions(session, submission_ids)
    return {sid: [serialize(r) for r in rows] for sid, rows in grouped.items()}


async def account_for(session: AsyncSession, user_id: uuid.UUID) -> GitHubAccount | None:
    return await session.get(GitHubAccount, user_id)


# --- Linking pull requests to a submission ---------------------------------------------------------


def _new_row(submission_id: uuid.UUID, ref: PullRequestRef, position: int) -> SubmissionPullRequest:
    return SubmissionPullRequest(
        id=uuid.uuid4(),
        submission_id=submission_id,
        url=ref.url,
        repo_owner=ref.owner,
        repo_name=ref.repo,
        number=ref.number,
        position=position,
        verification=PullRequestVerification.PENDING,
        snapshot={},
        next_check_at=utcnow(),
    )


async def sync_submission(session: AsyncSession, submission: BountySubmission, urls: Sequence[str]) -> None:
    """Makes the submission's linked pull requests exactly ``urls`` (already validated), keeping the snapshots
    of those that stay. Pure database work, so it belongs inside the submission's own transaction; the GitHub
    check runs after that transaction commits (``verify_submission``)."""
    refs = [ref for ref in (parse_pull_request_url(u) for u in urls) if ref is not None][:MAX_PULL_REQUESTS]
    existing = (await for_submissions(session, [submission.id])).get(submission.id, [])
    by_key = {(r.repo_owner, r.repo_name, r.number): r for r in existing}
    wanted = {(ref.owner, ref.repo, ref.number) for ref in refs}
    for key, row in by_key.items():
        if key not in wanted:
            await session.delete(row)
    for position, ref in enumerate(refs):
        kept = by_key.get((ref.owner, ref.repo, ref.number))
        if kept is None:
            session.add(_new_row(submission.id, ref, position))
        else:
            kept.position = position
    await session.flush()


# --- Checking: read plan -> GitHub -> one write transaction -------------------------------------------


@dataclass(frozen=True)
class _Plan:
    """What one check needs, read before GitHub is called so no transaction stays open during the request."""

    pull_request_id: uuid.UUID
    owner: str
    repo: str
    number: int
    repository_url: str | None
    contributor_github_id: int | None
    contributor_login: str | None


@dataclass(frozen=True)
class _Outcome:
    """What GitHub answered for one plan, applied to the row inside the write transaction."""

    plan: _Plan
    facts: PullRequestFacts | None = None
    checks: ChecksSummary | None = None
    missing: bool = False
    unavailable: str | None = None
    retry_at: datetime | None = None


async def _plans(session: AsyncSession, ids: Sequence[uuid.UUID]) -> list[_Plan]:
    """One joined query for every pull request to check, its bounty's repository and the contributor's
    verified GitHub account."""
    if not ids:
        return []
    rows = (
        await session.execute(
            select(
                SubmissionPullRequest.id,
                SubmissionPullRequest.repo_owner,
                SubmissionPullRequest.repo_name,
                SubmissionPullRequest.number,
                Bounty.repository_url,
                GitHubAccount.github_id,
                GitHubAccount.login,
            )
            .join(BountySubmission, BountySubmission.id == SubmissionPullRequest.submission_id)
            .join(Bounty, Bounty.id == BountySubmission.bounty_id)
            .outerjoin(GitHubAccount, GitHubAccount.user_id == BountySubmission.contributor_id)
            .where(SubmissionPullRequest.id.in_(ids))
            .order_by(SubmissionPullRequest.id)
        )
    ).all()
    return [_Plan(*row) for row in rows]


async def _expected_repo_id(client: GitHubClient, expected: tuple[str, str] | None) -> int | None:
    """The bounty repository's GitHub id, fetched only when the names differ (a renamed or transferred repo)."""
    if expected is None:
        return None
    try:
        repo = await client.get_repo(*expected)
    except (GitHubNotFound, GitHubUnavailable):
        return None
    value = repo.get("id")
    return value if isinstance(value, int) else None


async def _fetch(plan: _Plan, client: GitHubClient) -> _Outcome:
    """Reads one pull request and its checks from GitHub. No database session is involved."""
    expected = parse_repository_url(plan.repository_url)
    try:
        pr = await client.get_pull(plan.owner, plan.repo, plan.number)
    except GitHubNotFound:
        return _Outcome(plan, missing=True)
    except GitHubUnavailable as exc:
        return _Outcome(plan, unavailable=exc.message, retry_at=exc.retry_at)

    base_repo = (pr.get("base") or {}).get("repo") or {}
    names_match = expected is not None and str(base_repo.get("full_name") or "").lower() == "/".join(expected)
    repo_id = None if names_match else await _expected_repo_id(client, expected)
    facts = evaluate_pull_request(
        pr,
        expected_repo=expected,
        expected_repo_id=repo_id,
        contributor_github_id=plan.contributor_github_id,
        contributor_login=plan.contributor_login,
    )
    checks: ChecksSummary | None = None
    if facts.head_sha:
        owner, name = (facts.base_repo or f"{plan.owner}/{plan.repo}").split("/", 1)
        try:
            runs = await client.get_check_runs(owner, name, facts.head_sha)
            combined = await client.get_combined_status(owner, name, facts.head_sha)
            checks = summarize_checks(runs, combined)
        except GitHubNotFound:
            checks = summarize_checks(None, None)
        except GitHubUnavailable:
            checks = None  # keep the previous checks; the state and verdict above are fresh
    return _Outcome(plan, facts=facts, checks=checks)


def _interval(verification: PullRequestVerification) -> timedelta:
    if verification == PullRequestVerification.NOT_FOUND:
        return RECHECK_NOT_FOUND
    return RECHECK_AUTHENTICATED if get_settings().github_token else RECHECK_UNAUTHENTICATED


def _schedule(row: SubmissionPullRequest, now: datetime) -> datetime | None:
    """Open pull requests are re-checked until merged or closed; failures back off exponentially."""
    if row.consecutive_failures:
        return now + min(MAX_BACKOFF, FAILURE_BACKOFF * (2 ** min(row.consecutive_failures - 1, 10)))
    if row.state in TERMINAL_STATES and row.verification != PullRequestVerification.PENDING:
        return None
    return now + _interval(row.verification)


def _apply_outcome(row: SubmissionPullRequest, outcome: _Outcome, now: datetime) -> None:
    """Writes one GitHub answer onto a locked row. Applying the same answer twice leaves the same state."""
    if outcome.missing:
        row.verification = PullRequestVerification.NOT_FOUND
        row.detail = "This pull request was not found on GitHub. It may be private, or the URL may be wrong."
        row.state = None
        row.checks = None
        row.last_checked_at = now
        row.consecutive_failures = 0
        row.next_check_at = _schedule(row, now)
        return
    if outcome.facts is None:
        row.consecutive_failures += 1
        if row.last_checked_at is None:
            row.verification = PullRequestVerification.UNAVAILABLE
        row.detail = outcome.unavailable
        next_check = _schedule(row, now)
        if outcome.retry_at is not None and (next_check is None or outcome.retry_at > next_check):
            next_check = outcome.retry_at
        row.next_check_at = next_check
        return

    facts = outcome.facts
    row.verification = facts.verification
    row.detail = facts.detail
    row.state = facts.state
    row.title = facts.title
    row.author_login = facts.author_login
    row.author_id = facts.author_id
    row.base_repo = facts.base_repo
    row.merged_at = facts.merged_at
    row.head_sha = facts.head_sha
    snapshot = dict(row.snapshot or {})
    snapshot.update(
        {
            "html_url": facts.html_url,
            "draft": facts.draft,
            "head_ref": facts.head_ref,
            "base_ref": facts.base_ref,
        }
    )
    if outcome.checks is not None:
        checks = outcome.checks
        row.checks = checks.status
        row.checks_passed, row.checks_failed, row.checks_pending = (
            checks.passed,
            checks.failed,
            checks.pending,
        )
        snapshot["check_runs"] = checks.check_runs
        snapshot["statuses"] = checks.statuses
    row.snapshot = snapshot
    row.last_checked_at = now
    row.consecutive_failures = 0
    row.next_check_at = _schedule(row, now)


def _stage_update_event(
    session: AsyncSession,
    row: SubmissionPullRequest,
    submission: BountySubmission,
    previous: PullRequestState | None,
) -> None:
    bounty = submission.bounty
    add_event(
        session,
        event_type=EventType.SUBMISSION_PULL_REQUEST_UPDATED,
        aggregate_type="submission",
        aggregate_id=submission.id,
        payload={
            "submission_id": submission.id,
            "bounty_id": bounty.id,
            "requester_id": bounty.requester_id,
            "contributor_id": submission.contributor_id,
            "title": bounty.title,
            "status": submission.status.value,
            "version": submission.version,
            "pull_request_id": row.id,
            "repository": row.repository,
            "number": row.number,
            "state": row.state.value if row.state else None,
            "previous_state": previous.value if previous else None,
            "verification": row.verification.value,
        },
    )


async def _apply(session: AsyncSession, outcomes: Sequence[_Outcome]) -> int:
    """One transaction: lock the rows in id order, write every snapshot, stage the events, commit once."""
    if not outcomes:
        return 0
    by_id = {o.plan.pull_request_id: o for o in outcomes}
    rows = (
        await session.scalars(
            select(SubmissionPullRequest)
            .where(SubmissionPullRequest.id.in_(by_id))
            .order_by(SubmissionPullRequest.id)
            .with_for_update(of=SubmissionPullRequest)
            .execution_options(populate_existing=True)
        )
    ).all()
    submissions = {
        s.id: s
        for s in (
            await session.scalars(
                select(BountySubmission)
                .options(joinedload(BountySubmission.bounty))
                .where(BountySubmission.id.in_({r.submission_id for r in rows}))
            )
        )
        .unique()
        .all()
    }
    now = utcnow()
    written = 0
    for row in rows:
        previous = row.state
        _apply_outcome(row, by_id[row.id], now)
        written += 1
        submission = submissions.get(row.submission_id)
        if submission is not None and row.state != previous and row.state in TERMINAL_STATES:
            _stage_update_event(session, row, submission, previous)
    await session.commit()
    return written


async def verify_pull_requests(
    session: AsyncSession, ids: Sequence[uuid.UUID], *, client: GitHubClient | None = None
) -> int:
    """Checks the given pull requests against GitHub and records the result. The session must have no pending
    writes: its read transaction is closed before the first network call."""
    if not ids:
        return 0
    plans = await _plans(session, ids)
    await session.commit()  # end the read transaction; nothing is held while GitHub is called
    if not plans:
        return 0
    client = client or GitHubClient()
    outcomes = [await _fetch(plan, client) for plan in plans]
    return await _apply(session, outcomes)


async def verify_submission(session: AsyncSession, submission_id: uuid.UUID) -> int:
    rows = (await for_submissions(session, [submission_id])).get(submission_id, [])
    return await verify_pull_requests(session, [r.id for r in rows])


# --- Endpoints ----------------------------------------------------------------------------------------


async def _load_submission(session: AsyncSession, submission_id: uuid.UUID) -> BountySubmission:
    submission = await session.scalar(select(BountySubmission).where(BountySubmission.id == submission_id))
    if submission is None:
        raise NotFound("Submission not found.")
    return submission


def _can_read(submission: BountySubmission, user: User) -> bool:
    return (
        submission.contributor_id == user.id
        or submission.bounty.requester_id == user.id
        or has_permission(user, Permission.SUBMISSION_VIEW_ALL)
    )


async def list_for_submission(
    session: AsyncSession, user: User, submission_id: uuid.UUID
) -> list[PullRequestOut]:
    submission = await _load_submission(session, submission_id)
    if not _can_read(submission, user):
        raise NotFound("Submission not found.")
    rows = (await for_submissions(session, [submission.id])).get(submission.id, [])
    return [serialize(r) for r in rows]


async def recheck(session: AsyncSession, user: User, submission_id: uuid.UUID) -> list[PullRequestOut]:
    """On-demand re-check by the contributor, the requester or staff. Pull requests checked in the last few
    seconds are served from their snapshot so repeated clicks do not spend GitHub requests."""
    submission = await _load_submission(session, submission_id)
    if not _can_read(submission, user):
        raise NotFound("Submission not found.")
    await hit("github:recheck", str(user.id), 20, 300)
    rows = (await for_submissions(session, [submission.id])).get(submission.id, [])
    cutoff = utcnow() - MANUAL_COOLDOWN
    due = [r.id for r in rows if r.last_checked_at is None or r.last_checked_at < cutoff]
    await verify_pull_requests(session, due)
    return await list_for_submission(session, user, submission_id)


def _require_editable(submission: BountySubmission, user: User) -> None:
    if submission.contributor_id != user.id:
        raise NotFound("Submission not found.")
    if submission.status not in EDITABLE_SUBMISSIONS:
        raise InvalidStateTransition(
            f"Pull requests cannot be changed on a {submission.status.value.lower()} submission."
        )


async def add(session: AsyncSession, user: User, submission_id: uuid.UUID, url: str) -> PullRequestOut:
    submission = await _load_submission(session, submission_id)
    _require_editable(submission, user)
    ref = parse_pull_request_url(url)
    if ref is None:  # the schema validated it; this keeps the type checker honest
        raise ValidationFailed("Invalid pull request URL.")
    rows = (await for_submissions(session, [submission.id])).get(submission.id, [])
    if any((r.repo_owner, r.repo_name, r.number) == (ref.owner, ref.repo, ref.number) for r in rows):
        raise Conflict(f"{ref.label} is already linked to this submission.")
    if len(rows) >= MAX_PULL_REQUESTS:
        raise ValidationFailed(f"A submission can link at most {MAX_PULL_REQUESTS} pull requests.")
    row = _new_row(submission.id, ref, len(rows))
    session.add(row)
    await session.commit()  # the link is recorded first; GitHub is then called with nothing held
    await verify_pull_requests(session, [row.id])
    await session.refresh(row)
    return serialize(row)


async def remove(
    session: AsyncSession, user: User, submission_id: uuid.UUID, pull_request_id: uuid.UUID
) -> None:
    submission = await _load_submission(session, submission_id)
    _require_editable(submission, user)
    deleted = await session.scalar(
        delete(SubmissionPullRequest)
        .where(
            SubmissionPullRequest.id == pull_request_id,
            SubmissionPullRequest.submission_id == submission.id,
        )
        .returning(SubmissionPullRequest.id)
    )
    if deleted is None:
        raise NotFound("Pull request not found.")
    await session.commit()


# --- Scheduled and webhook-triggered re-checks -------------------------------------------------------


async def due_ids(session: AsyncSession, limit: int) -> list[uuid.UUID]:
    """Pull requests whose next check is due, on submissions that are still open (one joined query)."""
    now = utcnow()
    rows = await session.scalars(
        select(SubmissionPullRequest.id)
        .join(BountySubmission, BountySubmission.id == SubmissionPullRequest.submission_id)
        .where(
            SubmissionPullRequest.next_check_at.is_not(None),
            SubmissionPullRequest.next_check_at <= now,
            BountySubmission.status.in_(ACTIVE_SUBMISSIONS),
        )
        .order_by(SubmissionPullRequest.next_check_at)
        .limit(limit)
    )
    return list(rows.all())


async def stop_checking_closed_submissions(session: AsyncSession) -> int:
    """Approved or rejected submissions no longer need their pull requests re-checked."""
    result = await session.execute(
        update(SubmissionPullRequest)
        .where(
            SubmissionPullRequest.next_check_at.is_not(None),
            SubmissionPullRequest.submission_id.in_(
                select(BountySubmission.id).where(BountySubmission.status.not_in(ACTIVE_SUBMISSIONS))
            ),
        )
        .values(next_check_at=None)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def mark_due(
    session: AsyncSession,
    *,
    owner: str | None = None,
    repo: str | None = None,
    number: int | None = None,
    head_sha: str | None = None,
) -> int:
    """Schedules an immediate re-check of matching pull requests (webhook deliveries). One statement, one
    commit; the webhook never reads GitHub itself."""
    conditions: list[ColumnElement[bool]] = []
    if owner and repo and number is not None:
        conditions.append(
            (SubmissionPullRequest.repo_owner == owner.lower())
            & (SubmissionPullRequest.repo_name == repo.lower())
            & (SubmissionPullRequest.number == number)
        )
    if head_sha:
        conditions.append(SubmissionPullRequest.head_sha == head_sha)
    if not conditions:
        return 0
    result = await session.execute(
        update(SubmissionPullRequest)
        .where(
            or_(*conditions),
            SubmissionPullRequest.submission_id.in_(
                select(BountySubmission.id).where(BountySubmission.status.in_(ACTIVE_SUBMISSIONS))
            ),
        )
        .values(next_check_at=func.now(), consecutive_failures=0)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def reevaluate_authorship(
    session: AsyncSession, contributor_id: uuid.UUID, account: GitHubAccount | None
) -> int:
    """After a GitHub account is linked or unlinked, re-derives the authorship verdict of the contributor's
    checked pull requests from their stored author id — no GitHub request needed. Runs inside the caller's
    transaction and locks the rows it rewrites."""
    rows = (
        await session.scalars(
            select(SubmissionPullRequest)
            .join(BountySubmission, BountySubmission.id == SubmissionPullRequest.submission_id)
            .where(
                BountySubmission.contributor_id == contributor_id,
                SubmissionPullRequest.verification.in_(
                    [
                        PullRequestVerification.VERIFIED,
                        PullRequestVerification.AUTHOR_MISMATCH,
                        PullRequestVerification.AUTHOR_NOT_LINKED,
                    ]
                ),
                SubmissionPullRequest.author_id.is_not(None),
            )
            .order_by(SubmissionPullRequest.id)
            .with_for_update(of=SubmissionPullRequest)
        )
    ).all()
    for row in rows:
        if account is None:
            row.verification = PullRequestVerification.AUTHOR_NOT_LINKED
            row.detail = (
                "The contributor has not linked a verified GitHub account, so authorship is unconfirmed."
            )
        elif row.author_id == account.github_id:
            row.verification = PullRequestVerification.VERIFIED
            row.detail = None
        else:
            row.verification = PullRequestVerification.AUTHOR_MISMATCH
            row.detail = f"Opened by @{row.author_login}, not @{account.login}."
    return len(rows)


# --- Approval gate ------------------------------------------------------------------------------------


def _problem(row: SubmissionPullRequest, account: GitHubAccount | None, bounty: Bounty) -> str:
    label = f"{row.repository}#{row.number}"
    v = row.verification
    if v == PullRequestVerification.NOT_FOUND:
        return f"{label} was not found on GitHub."
    if v == PullRequestVerification.REPO_MISMATCH:
        expected = parse_repository_url(bounty.repository_url)
        where = "/".join(expected) if expected else "the bounty's repository"
        return f"{label} is in {row.base_repo or 'another repository'}, not {where}."
    if v in (PullRequestVerification.PENDING, PullRequestVerification.UNAVAILABLE):
        return f"{label} has not been verified yet because GitHub could not be reached. Try again in a few minutes."
    if account is None or v == PullRequestVerification.AUTHOR_NOT_LINKED:
        return (
            f"The contributor has not linked a GitHub account, so authorship of {label} cannot be verified."
        )
    if v == PullRequestVerification.AUTHOR_MISMATCH or row.author_id != account.github_id:
        return f"{label} was opened by @{row.author_login}, not the contributor's verified account @{account.login}."
    if row.state == PullRequestState.CLOSED:
        return f"{label} was closed without being merged."
    return f"{label} is still open."


def review_clock_note(submission: BountySubmission) -> str:
    """What an unmet pull request requirement means while the escrow's on-chain review clock runs.

    The contract is the only authority over that clock: nothing BountyFlow refuses off-chain stops it, and when
    the window passes the contributor can claim the reward. So a blocked approval is a reason to *answer*, not
    to stay silent, and the message says so (see docs/github.md, "Merged pull requests and the review clock").
    """
    if submission.onchain_state != OnchainReviewState.PENDING:
        return ""
    when = (
        f" until {submission.claimable_at.strftime('%d %b %Y, %H:%M UTC')}" if submission.claimable_at else ""
    )
    return (
        f" This work is recorded on-chain and its review clock is still running{when}: staying silent does not "
        "hold the reward — once the window passes the contributor can claim it. Request changes or reject "
        "on-chain with your wallet to stop the clock."
    )


def merge_requirement_problem(
    bounty: Bounty, rows: Sequence[SubmissionPullRequest], account: GitHubAccount | None
) -> str | None:
    """None when approval may proceed; otherwise the precise reason it is blocked."""
    if not bounty.require_merged_pr:
        return None
    if not rows:
        return (
            "This bounty requires a merged pull request from the contributor, and this submission links none."
        )
    for row in rows:
        if (
            row.verification == PullRequestVerification.VERIFIED
            and row.state == PullRequestState.MERGED
            and account is not None
            and row.author_id == account.github_id
        ):
            return None
    problems = [_problem(r, account, bounty) for r in rows]
    return "This bounty requires a merged pull request from the contributor. " + " ".join(problems[:3])


async def refresh_before_approval(session: AsyncSession, user: User, submission_id: uuid.UUID) -> None:
    """Before the requester approves on a bounty that requires a merged pull request, re-checks the
    submission's pull requests that are not yet merged and verified. Runs before the review takes its row
    locks, and only for the requester (so nobody else can spend GitHub requests through this path)."""
    submission = await session.scalar(select(BountySubmission).where(BountySubmission.id == submission_id))
    if (
        submission is None
        or not submission.bounty.require_merged_pr
        or submission.bounty.requester_id != user.id
    ):
        return
    rows = (await for_submissions(session, [submission.id])).get(submission.id, [])
    account = await account_for(session, submission.contributor_id)
    if merge_requirement_problem(submission.bounty, rows, account) is None:
        return
    cutoff = utcnow() - MANUAL_COOLDOWN
    stale = [
        r.id for r in rows if r.state != PullRequestState.MERGED and (r.last_checked_at or cutoff) <= cutoff
    ]
    await verify_pull_requests(session, stale)


async def ensure_merge_requirement(
    session: AsyncSession, bounty: Bounty, submission: BountySubmission
) -> None:
    """Raises 409 ``merged_pr_required`` when the bounty requires a merged pull request and none qualifies.

    Only approval is gated: requesting changes and rejecting stay open, and the message points there whenever
    the on-chain review clock is running."""
    if not bounty.require_merged_pr:
        return
    rows = (await for_submissions(session, [submission.id])).get(submission.id, [])
    account = await account_for(session, submission.contributor_id)
    problem = merge_requirement_problem(bounty, rows, account)
    if problem is not None:
        raise Conflict(
            problem + review_clock_note(submission),
            code="merged_pr_required",
            details={
                "pull_requests": [{"id": str(r.id), "verification": r.verification.value} for r in rows],
                "onchain_review_pending": submission.onchain_state == OnchainReviewState.PENDING,
                "claimable_at": submission.claimable_at.isoformat() if submission.claimable_at else None,
            },
        )


def ensure_repository_supports_merge_requirement(repository_url: str | None, require_merged_pr: bool) -> None:
    """A merged pull request can only be required when the bounty's repository (if any) is on GitHub."""
    if require_merged_pr and repository_url and parse_repository_url(repository_url) is None:
        raise ValidationFailed(
            "A merged pull request can only be required when the repository is on GitHub.",
            details=[
                {"field": "require_merged_pr", "message": "Use a https://github.com/owner/repo repository"}
            ],
        )
