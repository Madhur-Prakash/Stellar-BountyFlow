"""Analytics against PostgreSQL: exclusion rules, unique-hash counting, idempotent daily recomputation."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.modules.analytics import service as analytics
from app.modules.analytics.models import DailyMetric
from app.modules.applications.models import ApplicationStatus
from app.modules.bounties.models import BountyStatus
from app.modules.payments.models import TxStatus, TxType
from tests.integration.factories import (
    make_application,
    make_assignment,
    make_bounty,
    make_escrow,
    make_tx,
    make_user,
)

pytestmark = pytest.mark.integration


async def seed(session: AsyncSession) -> dict[str, object]:
    requester = await make_user(session)
    contributor = await make_user(session)
    other = await make_user(session)
    await make_user(session, is_active=False)

    live = await make_bounty(session, requester, status=BountyStatus.COMPLETED, completed_at=utcnow())
    open_bounty = await make_bounty(session, requester, status=BountyStatus.FUNDED)
    await make_bounty(session, requester, status=BountyStatus.DRAFT)
    await make_bounty(session, requester, status=BountyStatus.OPEN, is_hidden=True)
    hidden_bounty = await make_bounty(session, other, status=BountyStatus.FUNDED, is_hidden=True)

    await make_escrow(session, open_bounty, funded="100")
    await make_escrow(session, live, funded="100")
    await make_escrow(session, hidden_bounty, funded="100")

    wallet = "G" + "A" * 55
    await make_tx(
        session, bounty=live, tx_type=TxType.PAYOUT, amount="100", tx_hash="h-payout", source=wallet
    )
    await make_tx(
        session, bounty=open_bounty, tx_type=TxType.ESCROW_FUND, amount="100", tx_hash="h-fund", source=wallet
    )
    await make_tx(
        session, bounty=live, tx_type=TxType.PAYOUT, status=TxStatus.SUBMITTED, amount="999"
    )  # submitted, not yet verified on-chain: excluded
    await make_tx(session, bounty=hidden_bounty, tx_type=TxType.PAYOUT, amount="555")  # hidden: excluded
    await make_tx(
        session, bounty=live, tx_type=TxType.PAYOUT, amount="42", network="mainnet"
    )  # other network
    await make_tx(session, bounty=live, tx_type=TxType.PAYOUT, status=TxStatus.FAILED, amount="7")
    await make_tx(session, bounty=None, tx_type=TxType.WALLET_CHALLENGE, amount=None)  # never counted

    await make_assignment(session, live, contributor)
    other_live = await make_bounty(session, requester, status=BountyStatus.COMPLETED, completed_at=utcnow())
    await make_assignment(session, other_live, contributor)
    await make_application(session, open_bounty, await make_user(session), status=ApplicationStatus.REJECTED)
    await session.commit()
    return {"requester": requester, "contributor": contributor}


async def test_public_stats_apply_exclusion_rules(db_session: AsyncSession) -> None:
    await seed(db_session)
    stats = await analytics.compute_public_stats(db_session)
    assert stats.registered_users == 4  # requester, contributor, other, applicant (suspended excluded)
    assert stats.published_bounties == 3  # live, open, other_live (drafts and hidden excluded)
    assert stats.open_bounties == 1
    assert stats.completed_bounties == 2
    assert stats.funded_bounties == 2
    assert stats.verified_payout_volume == Decimal("100")
    assert stats.successful_transactions == 2  # payout + fund; unverified/hidden/mainnet/challenge excluded
    assert stats.unique_transacting_wallets == 1
    assert stats.network == "testnet"
    assert "verified_payout_volume" in stats.methodology
    assert "testnet" in stats.methodology["environment"]


async def test_public_stats_are_cached(db_session: AsyncSession) -> None:
    first = await analytics.get_public_stats(db_session)
    await make_user(db_session)
    await db_session.commit()
    second = await analytics.get_public_stats(db_session)
    assert second.registered_users == first.registered_users  # served from the 60 s cache
    assert second.model_dump(mode="json")["verified_payout_volume"] == "0.0000000"


async def test_platform_analytics(db_session: AsyncSession) -> None:
    await seed(db_session)
    platform = await analytics.platform_analytics(db_session)
    assert platform.engagement.repeat_contributors == 1
    assert platform.engagement.applications_decided == 3  # two accepted (assignments) + one rejected
    assert platform.engagement.application_acceptance_rate == pytest.approx(0.6667)
    assert platform.transactions.failed_transactions == 1
    assert len(platform.time_series) == 30
    assert platform.users.verified_users == platform.users.registered_users


async def test_personal_analytics(db_session: AsyncSession) -> None:
    people = await seed(db_session)
    requester = people["requester"]
    mine = await analytics.my_analytics(db_session, requester)  # type: ignore[arg-type]
    assert mine.requester.bounties_by_status["COMPLETED"] == 2
    assert mine.requester.bounties_by_status["DRAFT"] == 1
    assert set(mine.requester.bounties_by_status) >= {s.value for s in BountyStatus}
    assert mine.requester.total_escrowed == Decimal("200")
    assert len(mine.requester.spending_by_month) == 12
    contributor = await analytics.contributor_analytics(db_session, people["contributor"])  # type: ignore[arg-type]
    assert contributor.completed_count == 2
    assert contributor.applications_by_status["ACCEPTED"] == 2


async def test_recompute_day_is_idempotent(db_session: AsyncSession) -> None:
    await seed(db_session)
    today = utcnow().date()
    first = await analytics.recompute_day(db_session, today)
    await db_session.commit()
    second = await analytics.recompute_day(db_session, today)
    await db_session.commit()
    assert first == second
    assert first["payout_volume"] == Decimal("100")
    assert first["payouts_confirmed_count"] == 1
    assert first["bounties_funded"] == 1
    assert first["registrations"] == 5  # every account created today, including the suspended one
    rows = (await db_session.scalars(select(DailyMetric).where(DailyMetric.day == today))).all()
    assert len(rows) == len(first)
    yesterday = await analytics.recompute_day(db_session, today - timedelta(days=1))
    assert all(v == 0 for v in yesterday.values())
    series = await analytics.daily_series(db_session, today)
    assert series[-1].payout_volume == Decimal("100")
