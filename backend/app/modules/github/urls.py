"""Parsing of GitHub URLs (pull requests, repositories, gists) and logins. Pure functions, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# GitHub's own rules: 1-39 characters, alphanumerics and single hyphens, not starting or ending with one.
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_GIST_ID_RE = re.compile(r"^[0-9a-f]{5,64}$", re.IGNORECASE)
_HOSTS = {"github.com", "www.github.com"}

PULL_REQUEST_URL_HINT = "Use a GitHub pull request URL, like https://github.com/owner/repo/pull/123."


@dataclass(frozen=True)
class PullRequestRef:
    owner: str  # lower-cased
    repo: str  # lower-cased
    number: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"

    @property
    def label(self) -> str:
        return f"{self.full_name}#{self.number}"


def _path_parts(url: str, hosts: set[str]) -> list[str] | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in hosts:
        return None
    if parts.username or parts.password or parts.port not in (None, 443, 80):
        return None
    return [p for p in parts.path.split("/") if p]


def parse_pull_request_url(url: str) -> PullRequestRef | None:
    """``https://github.com/{owner}/{repo}/pull/{number}`` (tabs such as ``/files`` or ``/commits`` are fine)."""
    parts = _path_parts(url, _HOSTS)
    if not parts or len(parts) < 4 or parts[2] != "pull" or not parts[3].isdigit():
        return None
    owner, repo, number = parts[0], parts[1], int(parts[3])
    if not LOGIN_RE.match(owner) or not _NAME_RE.match(repo) or not 0 < number < 2**31:
        return None
    return PullRequestRef(owner.lower(), repo.lower().removesuffix(".git"), number)


def parse_repository_url(url: str | None) -> tuple[str, str] | None:
    """``https://github.com/{owner}/{repo}`` (optionally ``.git`` or a deeper path) as lower-cased parts, or None
    when the URL is not a GitHub repository."""
    if not url:
        return None
    parts = _path_parts(url, _HOSTS)
    if not parts or len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not LOGIN_RE.match(owner) or not _NAME_RE.match(repo):
        return None
    return owner.lower(), repo.lower()


def parse_gist_id(value: str) -> str | None:
    """A gist id from ``https://gist.github.com/{login}/{id}``, ``https://gist.github.com/{id}`` or the bare id."""
    value = value.strip()
    if _GIST_ID_RE.match(value):
        return value.lower()
    parts = _path_parts(value, {"gist.github.com"})
    if not parts:
        return None
    candidate = parts[1] if len(parts) >= 2 else parts[0]
    return candidate.lower() if _GIST_ID_RE.match(candidate) else None


def is_valid_login(login: str) -> bool:
    return bool(LOGIN_RE.match(login))
