"""Shared pytest fixtures.

Layout:
  * Event loop: a selector loop on Windows (psycopg's async driver does not support the proactor loop).
  * Database (integration tests only): a session-scoped engine on ``TEST_DATABASE_URL`` (never the
    development database). The schema is recreated once per session and every table is truncated after
    each test. Tests needing it are marked ``@pytest.mark.integration`` and are skipped when the database
    is not configured or not reachable.
  * Redis: fakeredis, installed for every test so nothing touches a real Redis.
  * Email: a capturing backend (``outbox_mail``) instead of SMTP.

API-level fixtures (httpx AsyncClient against app.main:app) build on ``db_engine`` / ``db_session``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Iterator
from typing import Any

import fakeredis
import pytest
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.cache import redis as cache_redis
from app.db import session as db_session_module
from app.db.base import Base

# --- Event loop ---------------------------------------------------------------------------------

if sys.platform == "win32":

    def pytest_asyncio_loop_factories(config: pytest.Config, item: pytest.Item) -> dict[str, Any]:
        return {"selector": asyncio.SelectorEventLoop}


# --- Configuration ---------------------------------------------------------------------------------


def _test_database_url() -> str | None:
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    root_env = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(root_env):
        return dotenv_values(root_env).get("TEST_DATABASE_URL") or None
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "integration" in item.nodeid.split("/"):
            item.add_marker(pytest.mark.integration)


# --- Redis (every test) ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache_redis.set_redis(client)
    try:
        yield client
    finally:
        await client.flushall()
        cache_redis.set_redis(None)  # type: ignore[arg-type]


# --- Email -------------------------------------------------------------------------------------------


class CapturingEmailBackend:
    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.fail_next = 0

    async def send(self, message: Any) -> None:
        from app.modules.notifications.email import EmailSendError

        if self.fail_next:
            self.fail_next -= 1
            raise EmailSendError("simulated SMTP outage")
        self.sent.append(message)


@pytest.fixture
def outbox_mail() -> Iterator[CapturingEmailBackend]:
    from app.modules.notifications.email import set_email_backend

    backend = CapturingEmailBackend()
    set_email_backend(backend)
    try:
        yield backend
    finally:
        set_email_backend(None)


# --- Database (integration) ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping integration tests")
    if url.rstrip("/").rsplit("/", 1)[-1] in {"bountyflow", "postgres"}:
        pytest.fail("TEST_DATABASE_URL must point to an isolated test database, not the development database")
    import app.db.models  # noqa: F401 - register all tables

    engine = create_async_engine(url, pool_size=5, max_overflow=5)
    try:
        async with asyncio.timeout(5):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"Test database unreachable: {type(exc).__name__}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    previous_engine = db_session_module._engine
    previous_sessionmaker = db_session_module._sessionmaker
    db_session_module.set_engine(engine)
    try:
        yield engine
    finally:
        db_session_module._engine = previous_engine
        db_session_module._sessionmaker = previous_sessionmaker
        await engine.dispose()


async def _truncate_all(engine: AsyncEngine) -> None:
    tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db(db_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Per-test database access with cleanup. Depend on this (not ``db_engine``) in tests."""
    db_session_module.set_engine(db_engine)
    try:
        yield db_engine
    finally:
        await _truncate_all(db_engine)


@pytest.fixture
async def db_session(db: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessionmaker = async_sessionmaker(db, expire_on_commit=False, autoflush=False)
    async with sessionmaker() as session:
        yield session
