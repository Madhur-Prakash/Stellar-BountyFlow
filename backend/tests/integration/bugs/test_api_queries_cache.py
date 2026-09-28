"""API input handling, query behaviour (search edge cases, N+1), counters, and cache invalidation."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.bounties.models import Bounty
from tests.integration.api.conftest import register
from tests.integration.bugs.helpers import (
    assign,
    contributor,
    funded,
    moderator,
    payout,
    published,
    requester,
    submit_work,
)


@contextmanager
def count_queries(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def before(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def test_invalid_status_filter_on_my_bounties_is_422(client_factory: Any) -> None:
    """BUG: `GET /bounties/mine?status=bogus` raised ValueError in the router -> 500."""
    user = client_factory()
    await register(user)
    response = await user.request("GET", "/bounties/mine", params={"status": "bogus"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    ok = await user.get("/bounties/mine", params={"status": "draft,open"})
    assert ok["total"] == 0


async def test_search_with_special_characters_never_500s(client_factory: Any, outbox_mail: Any) -> None:
    req, _ = await requester(client_factory, outbox_mail)
    await published(req, title="Escrow audit for 100% coverage_goal")
    anon = client_factory()
    for q in ["a:b & (c", "!!!", "'; drop table bounties; --", "(((", "\\", "a | b", "é漢字", "-", '"quoted']:
        page = await anon.get("/bounties", params={"q": q})
        assert isinstance(page["items"], list), q
    nul = await anon.request("GET", "/bounties", params={"q": "abc\x00def"})
    assert nul.status_code in (200, 422), nul.text


async def test_unbookmark_race_decrements_counter_once(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    """BUG: concurrent DELETE /bookmark requests each decremented bookmarks_count although only one row was
    deleted, drifting the popularity counter below the real number of bookmarks."""
    req, _ = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    bid = bounty["id"]
    fans = []
    for _ in range(2):
        fan = client_factory()
        await register(fan)
        await fan.post(f"/bounties/{bid}/bookmark", expected=204)
        fans.append(fan)
    await asyncio.gather(*[fans[0].request("DELETE", f"/bounties/{bid}/bookmark") for _ in range(4)])
    count = await db_session.scalar(
        select(Bounty.bookmarks_count).where(Bounty.id == bid).execution_options(populate_existing=True)
    )
    assert count == 1


async def test_open_bounty_deadline_cannot_be_moved_into_the_past(
    client_factory: Any, outbox_mail: Any
) -> None:
    """BUG: PATCH accepted past deadlines on a published bounty (publish validates them, update did not), so
    the next lifecycle run expired the bounty immediately."""
    req, _ = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    response = await req.request("PATCH", f"/bounties/{bounty['id']}", json={"application_deadline": past})
    assert response.status_code == 422
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    ok = await req.patch(f"/bounties/{bounty['id']}", {"application_deadline": future})
    assert ok["application_deadline"]


async def test_list_endpoints_do_not_issue_n_plus_one_queries(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, db: AsyncEngine
) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    mod = await moderator(client_factory, db_session)
    for n in range(4):
        bounty = await funded(req, wallet, title=f"Bounty number {n} for query counting", reward_amount="2")
        dev, _ = await contributor(client_factory)
        await assign(req, dev, bounty["id"])
        await dev.post(
            f"/bounties/{bounty['id']}/disputes",
            {"reason": "Opening a dispute for query counting."},
            expected=201,
        )

    async def cost(path: str, client: Any, **params: Any) -> int:
        with count_queries(db) as statements:
            await client.get(path, params=params)
        return len(statements)

    small = await cost("/admin/disputes", mod, page_size=1)
    large = await cost("/admin/disputes", mod, page_size=4)
    assert large <= small + 1, (small, large)
    small = await cost("/disputes/me", req)
    assert small <= 12, small
    anon = client_factory()
    small = await cost("/bounties", anon, page_size=1, status="in_progress")
    large = await cost("/bounties", anon, page_size=4, status="in_progress")
    assert large <= small + 1, (small, large)


async def test_profile_stats_are_invalidated_by_domain_changes(client_factory: Any, outbox_mail: Any) -> None:
    """BUG: cached profile stats (120 s) were not invalidated for the requester when their bounty completed,
    nor for a contributor when they applied."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    before = await dev.get(f"/users/{dev.me['username']}/stats")
    assert before["applications_submitted"] == 0
    await assign(req, dev, bid)
    after_apply = await dev.get(f"/users/{dev.me['username']}/stats")
    assert after_apply["applications_submitted"] == 1

    req_before = await req.get(f"/users/{req.me['username']}/stats")
    assert req_before["bounties_completed_as_requester"] == 0
    profile = await req.get(f"/users/{req.me['username']}")
    assert profile["stats"]["bounties_completed_as_requester"] == 0
    sub = await submit_work(dev, bid)
    await req.post(f"/submissions/{sub['id']}/approve", {})
    await payout(req, bid, wallet, sub["id"])
    req_after = await req.get(f"/users/{req.me['username']}/stats")
    assert req_after["bounties_completed_as_requester"] == 1
    profile = await req.get(f"/users/{req.me['username']}")
    assert profile["stats"]["bounties_completed_as_requester"] == 1


async def test_cached_payloads_never_carry_viewer_state(client_factory: Any, outbox_mail: Any) -> None:
    req, _ = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    bid = bounty["id"]
    fan = client_factory()
    await register(fan)
    await fan.post(f"/bounties/{bid}/bookmark", expected=204)
    fan_view = await fan.get(f"/bounties/{bid}")  # populates the detail cache
    assert fan_view["is_bookmarked"] is True and fan_view["viewer"]["is_owner"] is False
    owner_view = await req.get(f"/bounties/{bid}")  # served from the cache
    assert owner_view["is_bookmarked"] is False and owner_view["viewer"]["is_owner"] is True
    anon_view = await client_factory().get(f"/bounties/{bid}")
    assert anon_view["viewer"] is None and anon_view["is_bookmarked"] is False
    fan_list = await fan.get("/bounties")
    assert fan_list["items"][0]["is_bookmarked"] is True
    anon_list = await client_factory().get("/bounties")  # same cached page
    assert anon_list["items"][0]["is_bookmarked"] is False
