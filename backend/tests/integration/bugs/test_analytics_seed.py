"""Daily analytics metric correctness and the development seed (idempotency, no fabricated chain history,
resilience)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.config import get_network
from app.core.security import utcnow
from app.modules.analytics import service as analytics
from app.modules.applications.models import BountyApplication
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.payments.models import BlockchainTransaction, TxType
from app.modules.users.models import User
from tests.integration.factories import make_bounty, make_tx, make_user
from tests.support.fake_chain import FakeStellarChain


async def test_daily_bounties_funded_counts_funding_by_create_escrow(db_session: AsyncSession) -> None:
    """BUG: the daily `bounties_funded` metric only counted ESCROW_FUND transactions, but a bounty is normally
    funded in one ESCROW_CREATE (create + full deposit), so most funded bounties were never counted."""
    network = get_network().network
    today = utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    requester = await make_user(db_session)
    one_shot = await make_bounty(db_session, requester, status=BountyStatus.FUNDED)
    top_up = await make_bounty(db_session, requester, status=BountyStatus.FUNDED)
    for bounty, tx_type, when in (
        (one_shot, TxType.ESCROW_CREATE, today),
        (top_up, TxType.ESCROW_CREATE, today),  # partial deposit today...
        (top_up, TxType.ESCROW_FUND, tomorrow),  # ...completed tomorrow: counted once, on its first day
    ):
        await make_tx(
            db_session, bounty=bounty, tx_type=tx_type, amount="50", network=network, confirmed_at=when
        )
    await db_session.commit()
    assert (await analytics.compute_daily_metrics(db_session, today.date()))["bounties_funded"] == 2
    assert (await analytics.compute_daily_metrics(db_session, tomorrow.date()))["bounties_funded"] == 0


async def _counts(session: AsyncSession) -> tuple[int, int, int]:
    users = int(await session.scalar(select(func.count(User.id))) or 0)
    bounties = int(await session.scalar(select(func.count(Bounty.id))) or 0)
    txs = int(await session.scalar(select(func.count(BlockchainTransaction.id))) or 0)
    return users, bounties, txs


async def test_seed_is_idempotent_and_never_fabricates_chain_history(
    chain: FakeStellarChain, db: Any, db_session: AsyncSession
) -> None:
    from app.scripts.seed import BOUNTIES, USERS, seed

    first = await seed()
    assert first["users"] == len(USERS) and first["bounties_created"] == len(BOUNTIES)
    after_first = await _counts(db_session)
    assert after_first[2] == 0  # no chain history is ever fabricated on a real network
    second = await seed()
    assert second == {
        "users": 0,
        "users_updated": 0,
        "bounties_created": 0,
        "bounties_existing": len(BOUNTIES),
    }
    assert await _counts(db_session) == after_first
    rows = (await db_session.execute(select(Bounty.metadata_["seed_key"].astext, Bounty.status))).all()
    statuses = {key: status for key, status in rows}
    assert statuses.pop("draft-mobile-app") == BountyStatus.DRAFT
    assert set(statuses.values()) == {BountyStatus.OPEN}  # anything beyond OPEN needs a real signed funding
    applications = int(await db_session.scalar(select(func.count(BountyApplication.id))) or 0)
    assert applications == sum(len(b.applicants) for b in BOUNTIES if b.stage != "draft")
    assert chain.submitted == [] and chain.storage == {}  # the seed never touches the chain


async def test_seed_upgrades_accounts_created_by_older_seeds(
    chain: FakeStellarChain, db: Any, db_session: AsyncSession
) -> None:
    """BUG: an account created by an older seed under its current username (nova-labs) kept its old
    `@demo.bountyflow.local` email and password, so the printed sign-in details did not work for it."""
    from app.core.security import verify_password
    from app.scripts.seed import LEGACY_EMAIL_DOMAIN, seed

    renamed = await make_user(
        db_session, username="demo-requester", email=f"demo-requester{LEGACY_EMAIL_DOMAIN}"
    )
    renamed.normalized_email = renamed.email
    same_name = await make_user(db_session, username="nova-labs", email=f"nova-labs{LEGACY_EMAIL_DOMAIN}")
    same_name.normalized_email = same_name.email
    owned = await make_user(db_session, username="river-chen", email="river@example.com")
    owned.normalized_email = owned.email
    await db_session.commit()
    ids = {"ada-okafor": renamed.id, "nova-labs": same_name.id, "river-chen": owned.id}

    summary = await seed()
    assert summary["users_updated"] == 2

    db_session.expire_all()
    for username, email in (
        ("ada-okafor", "ada.okafor@bountyflow.test"),
        ("nova-labs", "nova.labs@bountyflow.test"),
    ):
        user = await db_session.get(User, ids[username])
        assert user is not None
        assert (user.username, user.email) == (username, email)  # same row: its history is kept
        assert verify_password(user.password_hash, "BountyFlow!2026")
    river = await db_session.get(User, ids["river-chen"])
    assert (
        river is not None and river.email == "river@example.com"
    )  # details its owner changed are left alone
    assert (await seed())["users_updated"] == 0


async def test_seed_continues_after_one_bounty_fails(
    app: Any, monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    """BUG: after one bounty failed, `session.rollback()` expired the cached seed users, so every later bounty
    failed too (lazy load outside the async context -> MissingGreenlet)."""
    from app.scripts import seed as seed_module

    good = next(b for b in seed_module.BOUNTIES if b.key == "grafana-dashboards")
    broken = dataclasses.replace(
        next(b for b in seed_module.BOUNTIES if b.key == "i18n-support"), applicants=["no-such-user"]
    )
    monkeypatch.setattr(seed_module, "BOUNTIES", [broken, good])
    await seed_module.seed()
    keys = set((await db_session.scalars(select(Bounty.metadata_["seed_key"].astext))).all())
    assert "grafana-dashboards" in keys
