"""Verified GitHub accounts and the pull requests linked to submissions, with their latest verification."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey
from app.db.types import str_enum


class GitHubLinkMethod(StrEnum):
    GIST = "GIST"  # a public gist holding a one-time challenge, owned by the claimed login
    OAUTH = "OAUTH"  # "Connect with GitHub" (only when an OAuth app is configured)


class PullRequestState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"  # closed without being merged
    MERGED = "MERGED"


class ChecksStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PENDING = "PENDING"
    NONE = "NONE"  # the head commit has no check runs or commit statuses


class PullRequestVerification(StrEnum):
    PENDING = "PENDING"  # not checked yet
    VERIFIED = "VERIFIED"  # exists, in the bounty's repository, opened by the contributor's verified login
    NOT_FOUND = "NOT_FOUND"
    REPO_MISMATCH = "REPO_MISMATCH"
    AUTHOR_MISMATCH = "AUTHOR_MISMATCH"
    AUTHOR_NOT_LINKED = "AUTHOR_NOT_LINKED"  # the contributor has no verified GitHub account
    UNAVAILABLE = "UNAVAILABLE"  # GitHub could not be reached (or rate-limited) and nothing was checked yet


class GitHubAccount(Timestamps, Base):
    """At most one GitHub account per BountyFlow user, and one BountyFlow user per GitHub account."""

    __tablename__ = "github_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    login: Mapped[str] = mapped_column(String(39), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    method: Mapped[GitHubLinkMethod] = mapped_column(
        str_enum(GitHubLinkMethod, "github_link_method"), nullable=False
    )
    # The gist that proved ownership (GIST links only).
    proof_url: Mapped[str | None] = mapped_column(String(500))
    verified_at: Mapped[datetime] = mapped_column(nullable=False)


class SubmissionPullRequest(UUIDPrimaryKey, Timestamps, Base):
    """A pull request linked to a submission and its latest verification snapshot. Open pull requests are
    re-checked on a schedule (worker), on demand, and on webhook deliveries until they are merged or closed."""

    __tablename__ = "submission_pull_requests"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "repo_owner", "repo_name", "number", name="uq_submission_pull_requests_pr"
        ),
        Index("ix_submission_pull_requests_repo_number", "repo_owner", "repo_name", "number"),
        Index("ix_submission_pull_requests_next_check_at", "next_check_at"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bounty_submissions.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Lower-cased from the URL; GitHub owner and repository names are case-insensitive.
    repo_owner: Mapped[str] = mapped_column(String(100), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(100), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    verification: Mapped[PullRequestVerification] = mapped_column(
        str_enum(PullRequestVerification, "pr_verification"),
        nullable=False,
        default=PullRequestVerification.PENDING,
    )
    state: Mapped[PullRequestState | None] = mapped_column(str_enum(PullRequestState, "pr_state"))
    title: Mapped[str | None] = mapped_column(String(300))
    author_login: Mapped[str | None] = mapped_column(String(39))
    author_id: Mapped[int | None] = mapped_column(BigInteger)
    base_repo: Mapped[str | None] = mapped_column(String(200))  # "owner/name" as GitHub reports it
    merged_at: Mapped[datetime | None]
    head_sha: Mapped[str | None] = mapped_column(String(40), index=True)
    checks: Mapped[ChecksStatus | None] = mapped_column(str_enum(ChecksStatus, "pr_checks_status"))
    checks_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    checks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    checks_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Why the last check did not verify (or why GitHub could not be reached), in plain words.
    detail: Mapped[str | None] = mapped_column(String(300))
    # {"html_url", "draft", "head_ref", "base_ref", "check_runs": [{name, status, conclusion}], "statuses": [...]}
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_checked_at: Mapped[datetime | None]
    next_check_at: Mapped[datetime | None]
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    @property
    def repository(self) -> str:
        return self.base_repo or f"{self.repo_owner}/{self.repo_name}"
