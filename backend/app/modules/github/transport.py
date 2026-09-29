"""The HTTP transport behind the GitHub client.

Production sends real requests (``None`` means httpx's default network transport). Tests inject an
``httpx.MockTransport`` with ``set_transport``. ``GITHUB_FIXTURE_TRANSPORT=true`` serves recorded GitHub API
responses from ``backend/tests/fixtures/github`` so the end-to-end suite exercises the real verification code
without calling GitHub or depending on anyone's gist; settings validation refuses it outside development and
test, and it is never part of a production image.
"""

from __future__ import annotations

import httpx

from app.core.config import get_settings

_override: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _override
    _override = transport


def get_transport() -> httpx.AsyncBaseTransport | None:
    if _override is not None:
        return _override
    settings = get_settings()
    if settings.github_fixture_transport and settings.app_env in ("development", "test"):
        from tests.support.github_fixtures import fixture_transport  # test-only module, loaded on demand

        return fixture_transport()
    return None
