"""GitHub account and pull request schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.core.schemas import APIModel, UrlStr
from app.modules.github.models import (
    ChecksStatus,
    GitHubLinkMethod,
    PullRequestState,
    PullRequestVerification,
)
from app.modules.github.urls import PULL_REQUEST_URL_HINT, is_valid_login, parse_pull_request_url

MAX_PULL_REQUESTS = 5


def validate_pull_request_urls(urls: list[str]) -> list[str]:
    """Canonical, de-duplicated pull request URLs (``https://github.com/owner/repo/pull/N``)."""
    seen: dict[str, None] = {}
    for url in urls:
        ref = parse_pull_request_url(url)
        if ref is None:
            raise ValueError(PULL_REQUEST_URL_HINT)
        seen.setdefault(ref.url, None)
    return list(seen)


class GitHubConfigOut(APIModel):
    oauth_enabled: bool
    webhook_enabled: bool
    authenticated_api: bool  # a GITHUB_TOKEN is configured (higher rate limit, faster re-checks)


class GitHubAccountOut(APIModel):
    github_id: int
    login: str
    avatar_url: str | None
    profile_url: str
    method: GitHubLinkMethod
    proof_url: str | None
    verified_at: datetime


class PublicGitHubAccount(APIModel):
    login: str
    avatar_url: str | None
    profile_url: str
    verified_at: datetime


class ChallengeRequest(APIModel):
    login: str = Field(min_length=1, max_length=39)

    @field_validator("login")
    @classmethod
    def _login(cls, v: str) -> str:
        v = v.strip().removeprefix("@")
        if not is_valid_login(v):
            raise ValueError("Enter your GitHub username, like octocat")
        return v


class ChallengeOut(APIModel):
    login: str
    challenge: str
    filename: str
    expires_at: datetime


class GistVerifyRequest(APIModel):
    gist_url: str = Field(min_length=5, max_length=500)


class OAuthStartOut(APIModel):
    authorize_url: str


class OAuthCallbackRequest(APIModel):
    code: str = Field(min_length=1, max_length=200)
    state: str = Field(min_length=16, max_length=200)


class PullRequestAdd(APIModel):
    url: UrlStr

    @field_validator("url")
    @classmethod
    def _pull_request(cls, v: str) -> str:
        return validate_pull_request_urls([v])[0]


class CheckRunOut(APIModel):
    name: str | None
    status: str | None
    conclusion: str | None


class CommitStatusOut(APIModel):
    context: str | None
    state: str | None


class PullRequestOut(APIModel):
    id: uuid.UUID
    url: str
    repository: str
    number: int
    verification: PullRequestVerification
    detail: str | None
    state: PullRequestState | None
    title: str | None
    author_login: str | None
    merged_at: datetime | None
    head_sha: str | None
    draft: bool
    checks: ChecksStatus | None
    checks_passed: int
    checks_failed: int
    checks_pending: int
    check_runs: list[CheckRunOut] = Field(default_factory=list)
    statuses: list[CommitStatusOut] = Field(default_factory=list)
    last_checked_at: datetime | None
    next_check_at: datetime | None
