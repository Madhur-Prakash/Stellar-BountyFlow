"""Analytics queries: public marketplace stats, personal requester/contributor dashboards, platform metrics,
and the idempotent daily-metric recomputation used by the analytics worker. See ``rules`` for definitions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.config import get_network
from app.cache import keys
from app.cache.redis import cached_json
from app.core.security import utcnow
from app.modules.analytics import rules
from app.modules.analytics.models import DailyMetric
from app.modules.analytics.schemas import (
    ContributorAnalytics,
    DailyPoint,
    MonthlyAmount,
    MyAnalytics,
    PlatformAnalytics,
    PlatformBounties,
    PlatformEngagement,
    PlatformTransactions,
    PlatformUsers,
    PublicStats,
    RequesterAnalytics,
)
from app.modules.applications.models import (
    ApplicationStatus,
    AssignmentStatus,
    BountyApplication,
    BountyAssignment,
)
from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.payments.models import (
    BlockchainTransaction,
    BountyEscrow,
    PaymentRecord,
    PaymentStatus,
    TxType,
)
from app.modules.submissions.models import BountySubmission, SubmissionStatus
from app.modules.users.models import User, Wallet, WalletVerificationStatus

ZERO = Decimal(0)


def _dec(value: Any) -> Decimal:
    return Decimal(value) if value is not None else ZERO


def _utc_month(column: Any) -> Any:
    return func.to_char(func.timezone("UTC", column), "YYYY-MM")


def _months_start(today: date, months: int = rules.MONTHS) -> datetime:
    first_month = rules.last_n_months(today, months)[0]
    year, month = (int(p) for p in first_month.split("-"))
    return rules.day_bounds(date(year, month, 1))[0]


# --- Shared building blocks ---------------------------------------------------------------------


async def _count(session: AsyncSession, stmt: Select[Any]) -> int:
    return int(await session.scalar(stmt) or 0)


def _live_tx_base(network: str) -> Select[str | None, str | None]:
    return (
        select(BlockchainTransaction.transaction_hash, BlockchainTransaction.source_address)
        .select_from(BlockchainTransaction)
        .outerjoin(Bounty, Bounty.id == BlockchainTransaction.bounty_id)
        .where(rules.live_transaction(network), rules.visible_bounty_tx())
    )


async def _bounty_counts(session: AsyncSession, network: str) -> dict[str, int]:
    # Scoped to the active network so a database that switched chain modes never mixes counts.
    row = (
        await session.execute(
            select(
                func.count(Bounty.id).filter(rules.published_bounty()),
                func.count(Bounty.id).filter(
                    rules.published_bounty(), Bounty.status.in_(rules.OPEN_STATUSES)
                ),
                func.count(Bounty.id).filter(rules.visible_bounty(), Bounty.status == BountyStatus.COMPLETED),
            ).where(Bounty.network == network)
        )
    ).one()
    funded = await _count(
        session,
        select(func.count(distinct(Bounty.id)))
        .join(BountyEscrow, BountyEscrow.bounty_id == Bounty.id)
        .where(
            rules.visible_bounty(),
            Bounty.network == network,
            BountyEscrow.funded_amount > 0,
        ),
    )
    return {"published": row[0], "open": row[1], "completed": row[2], "funded": funded}


async def _transaction_metrics(session: AsyncSession, network: str) -> dict[str, Any]:
    live = _live_tx_base(network).subquery()
    row = (
        await session.execute(
            select(func.count(distinct(live.c.transaction_hash)), func.count(distinct(live.c.source_address)))
        )
    ).one()
    # One amount per unique hash: a retried verification can never double-count volume.
    payouts = (
        select(BlockchainTransaction.transaction_hash, func.max(BlockchainTransaction.amount).label("amount"))
        .outerjoin(Bounty, Bounty.id == BlockchainTransaction.bounty_id)
        .where(
            rules.live_transaction(network),
            rules.visible_bounty_tx(),
            BlockchainTransaction.transaction_type == TxType.PAYOUT,
        )
        .group_by(BlockchainTransaction.transaction_hash)
        .subquery()
    )
    volume = await session.scalar(select(func.coalesce(func.sum(payouts.c.amount), 0)))
    failed = await _count(
        session,
        select(func.count(distinct(BlockchainTransaction.id)))
        .outerjoin(Bounty, Bounty.id == BlockchainTransaction.bounty_id)
        .where(rules.failed_transaction(network), rules.visible_bounty_tx()),
    )
    return {"successful": row[0], "wallets": row[1], "volume": _dec(volume), "failed": failed}


# --- Public --------------------------------------------------------------------------------------


async def compute_public_stats(session: AsyncSession) -> PublicStats:
    net = get_network()
    users = await _count(session, select(func.count(User.id)).where(rules.active_user()))
    bounties = await _bounty_counts(session, net.network)
    tx = await _transaction_metrics(session, net.network)
    return PublicStats(
        network=net.network,
        generated_at=utcnow(),
        registered_users=users,
        published_bounties=bounties["published"],
        open_bounties=bounties["open"],
        funded_bounties=bounties["funded"],
        completed_bounties=bounties["completed"],
        verified_payout_volume=tx["volume"],
        successful_transactions=tx["successful"],
        unique_transacting_wallets=tx["wallets"],
        methodology=rules.public_methodology(net.network),
    )


async def get_public_stats(session: AsyncSession) -> PublicStats:
    async def load() -> dict[str, Any]:
        return (await compute_public_stats(session)).model_dump(mode="json")

    return PublicStats.model_validate(await cached_json(keys.public_stats(), keys.TTL_PUBLIC_STATS, load))


# --- Personal ------------------------------------------------------------------------------------


async def requester_analytics(session: AsyncSession, user: User) -> RequesterAnalytics:
    network = get_network().network
    today = utcnow().date()
    status_rows = (
        await session.execute(
            select(Bounty.status, func.count(Bounty.id))
            .where(Bounty.requester_id == user.id)
            .group_by(Bounty.status)
        )
    ).all()
    escrowed = await session.scalar(
        select(func.coalesce(func.sum(BountyEscrow.funded_amount), 0))
        .join(Bounty, Bounty.id == BountyEscrow.bounty_id)
        .where(Bounty.requester_id == user.id, Bounty.network == network)
    )
    paid_filter = and_(
        Bounty.requester_id == user.id,
        PaymentRecord.payment_status == PaymentStatus.CONFIRMED,
        rules.network_payment(network),
    )
    paid = await session.scalar(
        select(func.coalesce(func.sum(PaymentRecord.amount), 0))
        .join(Bounty, Bounty.id == PaymentRecord.bounty_id)
        .where(paid_filter)
    )
    applications = await _count(
        session,
        select(func.count(BountyApplication.id))
        .join(Bounty, Bounty.id == BountyApplication.bounty_id)
        .where(Bounty.requester_id == user.id),
    )
    first_app = (
        select(BountyApplication.bounty_id, func.min(BountyApplication.created_at).label("first_at"))
        .group_by(BountyApplication.bounty_id)
        .subquery()
    )
    avg_seconds = await session.scalar(
        select(func.avg(func.extract("epoch", first_app.c.first_at - Bounty.published_at)))
        .join(first_app, first_app.c.bounty_id == Bounty.id)
        .where(
            Bounty.requester_id == user.id,
            Bounty.published_at.is_not(None),
            first_app.c.first_at >= Bounty.published_at,
        )
    )
    settled = func.coalesce(PaymentRecord.settled_at, PaymentRecord.created_at)
    month_rows = (
        await session.execute(
            select(_utc_month(settled).label("month"), func.sum(PaymentRecord.amount))
            .join(Bounty, Bounty.id == PaymentRecord.bounty_id)
            .where(paid_filter, settled >= _months_start(today))
            .group_by("month")
        )
    ).all()
    return RequesterAnalytics(
        bounties_by_status=rules.zero_filled(
            [s.value for s in BountyStatus], {s.value: c for s, c in status_rows}
        ),
        total_escrowed=_dec(escrowed),
        total_paid=_dec(paid),
        applications_received=applications,
        avg_time_to_first_application_hours=round(float(avg_seconds) / 3600, 2)
        if avg_seconds is not None
        else None,
        spending_by_month=[
            MonthlyAmount(**m) for m in rules.fill_months(((r[0], r[1]) for r in month_rows), today)
        ],
    )


async def contributor_analytics(session: AsyncSession, user: User) -> ContributorAnalytics:
    network = get_network().network
    today = utcnow().date()
    app_rows = (
        await session.execute(
            select(BountyApplication.status, func.count(BountyApplication.id))
            .where(BountyApplication.contributor_id == user.id)
            .group_by(BountyApplication.status)
        )
    ).all()
    sub_rows = (
        await session.execute(
            select(BountySubmission.status, func.count(BountySubmission.id))
            .where(BountySubmission.contributor_id == user.id)
            .group_by(BountySubmission.status)
        )
    ).all()
    earned_filter = and_(
        PaymentRecord.contributor_id == user.id,
        PaymentRecord.payment_status == PaymentStatus.CONFIRMED,
        rules.network_payment(network),
    )
    earned = await session.scalar(
        select(func.coalesce(func.sum(PaymentRecord.amount), 0)).where(earned_filter)
    )
    settled = func.coalesce(PaymentRecord.settled_at, PaymentRecord.created_at)
    month_rows = (
        await session.execute(
            select(_utc_month(settled).label("month"), func.sum(PaymentRecord.amount))
            .where(earned_filter, settled >= _months_start(today))
            .group_by("month")
        )
    ).all()
    completed = await _count(
        session,
        select(func.count(BountyAssignment.id)).where(
            BountyAssignment.contributor_id == user.id, BountyAssignment.status == AssignmentStatus.COMPLETED
        ),
    )
    return ContributorAnalytics(
        applications_by_status=rules.zero_filled(
            [s.value for s in ApplicationStatus], {s.value: c for s, c in app_rows}
        ),
        submissions_by_status=rules.zero_filled(
            [s.value for s in SubmissionStatus], {s.value: c for s, c in sub_rows}
        ),
        total_earned=_dec(earned),
        earnings_by_month=[
            MonthlyAmount(**m) for m in rules.fill_months(((r[0], r[1]) for r in month_rows), today)
        ],
        completed_count=completed,
    )


async def my_analytics(session: AsyncSession, user: User) -> MyAnalytics:
    return MyAnalytics(
        requester=await requester_analytics(session, user),
        contributor=await contributor_analytics(session, user),
    )


# --- Platform ------------------------------------------------------------------------------------


async def platform_analytics(session: AsyncSession) -> PlatformAnalytics:
    net = get_network()
    now = utcnow()
    user_row = (
        await session.execute(
            select(
                func.count(User.id),
                func.count(User.id).filter(User.email_verified_at.is_not(None)),
                func.count(User.id).filter(User.last_login_at >= now - timedelta(days=30)),
            ).where(rules.active_user())
        )
    ).one()
    wallets = await _count(
        session,
        select(func.count(distinct(Wallet.user_id)))
        .join(User, User.id == Wallet.user_id)
        .where(
            rules.active_user(),
            Wallet.verification_status == WalletVerificationStatus.VERIFIED,
            Wallet.network == net.network,
        ),
    )
    bounties = await _bounty_counts(session, net.network)
    tx = await _transaction_metrics(session, net.network)

    repeat_sub = (
        select(BountyAssignment.contributor_id)
        .join(Bounty, Bounty.id == BountyAssignment.bounty_id)
        .join(User, User.id == BountyAssignment.contributor_id)
        .where(
            BountyAssignment.status == AssignmentStatus.COMPLETED,
            rules.active_user(),
            Bounty.is_hidden.is_(False),
        )
        .group_by(BountyAssignment.contributor_id)
        .having(func.count(BountyAssignment.id) >= 2)
        .subquery()
    )
    repeat = await _count(session, select(func.count()).select_from(repeat_sub))
    app_row = (
        await session.execute(
            select(
                func.count(BountyApplication.id).filter(
                    BountyApplication.status == ApplicationStatus.ACCEPTED
                ),
                func.count(BountyApplication.id).filter(
                    BountyApplication.status.in_([ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED])
                ),
            )
            .join(Bounty, Bounty.id == BountyApplication.bounty_id)
            .where(Bounty.is_hidden.is_(False))
        )
    ).one()
    sub_row = (
        await session.execute(
            select(
                func.count(BountySubmission.id).filter(BountySubmission.status == SubmissionStatus.APPROVED),
                func.count(BountySubmission.id).filter(
                    BountySubmission.status.in_([SubmissionStatus.APPROVED, SubmissionStatus.REJECTED])
                ),
            )
            .join(Bounty, Bounty.id == BountySubmission.bounty_id)
            .where(Bounty.is_hidden.is_(False))
        )
    ).one()
    registered, verified, active = user_row
    return PlatformAnalytics(
        network=net.network,
        generated_at=now,
        users=PlatformUsers(
            registered_users=registered,
            verified_users=verified,
            connected_wallets=wallets,
            active_users_30d=active,
            email_verification_rate=rules.rate(verified, registered),
            wallet_connection_rate=rules.rate(wallets, registered),
        ),
        bounties=PlatformBounties(
            published_bounties=bounties["published"],
            open_bounties=bounties["open"],
            funded_bounties=bounties["funded"],
            completed_bounties=bounties["completed"],
        ),
        transactions=PlatformTransactions(
            unique_transacting_wallets=tx["wallets"],
            successful_transactions=tx["successful"],
            failed_transactions=tx["failed"],
            verified_payout_volume=tx["volume"],
        ),
        engagement=PlatformEngagement(
            repeat_contributors=repeat,
            applications_decided=app_row[1],
            application_acceptance_rate=rules.rate(app_row[0], app_row[1]),
            submissions_reviewed=sub_row[1],
            submission_approval_rate=rules.rate(sub_row[0], sub_row[1]),
        ),
        time_series=await daily_series(session, now.date()),
        methodology=rules.platform_methodology(net.network),
    )


async def daily_series(session: AsyncSession, end: date, days: int = rules.SERIES_DAYS) -> list[DailyPoint]:
    window = rules.last_n_days(end, days)
    rows = (
        await session.execute(
            select(DailyMetric.day, DailyMetric.metric, DailyMetric.value).where(
                DailyMetric.day >= window[0], DailyMetric.day <= window[-1]
            )
        )
    ).all()
    values: dict[date, dict[str, Decimal]] = {}
    for day, metric, value in rows:
        values.setdefault(day, {})[metric] = value
    return [build_daily_point(day, values.get(day, {})) for day in window]


def build_daily_point(day: date, metrics: dict[str, Decimal]) -> DailyPoint:
    counts = {m: int(metrics.get(m, ZERO)) for m in rules.DAILY_METRICS if m != "payout_volume"}
    return DailyPoint(day=day, payout_volume=metrics.get("payout_volume", ZERO), **counts)


# --- Daily metric recomputation (analytics worker) -------------------------------------------------


async def compute_daily_metrics(session: AsyncSession, day: date) -> dict[str, Decimal]:
    """Recompute every daily metric for one UTC day from the source tables."""
    network = get_network().network
    start, end = rules.day_bounds(day)

    def within(column: Any) -> Any:
        return and_(column >= start, column < end)

    registrations = await _count(session, select(func.count(User.id)).where(within(User.created_at)))
    bounty_row = (
        await session.execute(
            select(
                func.count(Bounty.id).filter(within(Bounty.published_at)),
                func.count(Bounty.id).filter(
                    within(Bounty.completed_at), Bounty.status == BountyStatus.COMPLETED
                ),
            ).where(Bounty.is_hidden.is_(False))
        )
    ).one()
    # A bounty counts as funded on the day its escrow first received funds: usually a single ESCROW_CREATE
    # (create + full deposit), otherwise the first partial deposit. Each bounty is counted once, on that day.
    first_funding = (
        select(
            BlockchainTransaction.bounty_id,
            func.min(BlockchainTransaction.confirmed_at).label("first_at"),
        )
        .outerjoin(Bounty, Bounty.id == BlockchainTransaction.bounty_id)
        .where(
            rules.live_transaction(network),
            rules.visible_bounty_tx(),
            BlockchainTransaction.bounty_id.is_not(None),
            BlockchainTransaction.transaction_type.in_([TxType.ESCROW_CREATE, TxType.ESCROW_FUND]),
        )
        .group_by(BlockchainTransaction.bounty_id)
        .subquery()
    )
    funded = await _count(
        session, select(func.count()).select_from(first_funding).where(within(first_funding.c.first_at))
    )
    applications = await _count(
        session,
        select(func.count(BountyApplication.id))
        .join(Bounty, Bounty.id == BountyApplication.bounty_id)
        .where(Bounty.is_hidden.is_(False), within(BountyApplication.created_at)),
    )
    submissions = await _count(
        session,
        select(func.count(BountySubmission.id))
        .join(Bounty, Bounty.id == BountySubmission.bounty_id)
        .where(Bounty.is_hidden.is_(False), within(BountySubmission.created_at)),
    )
    payouts = (
        select(BlockchainTransaction.transaction_hash, func.max(BlockchainTransaction.amount).label("amount"))
        .outerjoin(Bounty, Bounty.id == BlockchainTransaction.bounty_id)
        .where(
            rules.live_transaction(network),
            rules.visible_bounty_tx(),
            BlockchainTransaction.transaction_type == TxType.PAYOUT,
            within(BlockchainTransaction.confirmed_at),
        )
        .group_by(BlockchainTransaction.transaction_hash)
        .subquery()
    )
    payout_row = (
        await session.execute(
            select(func.count(payouts.c.transaction_hash), func.coalesce(func.sum(payouts.c.amount), 0))
        )
    ).one()
    return {
        "registrations": Decimal(registrations),
        "bounties_published": Decimal(bounty_row[0]),
        "bounties_funded": Decimal(funded),
        "bounties_completed": Decimal(bounty_row[1]),
        "applications": Decimal(applications),
        "submissions": Decimal(submissions),
        "payouts_confirmed_count": Decimal(payout_row[0]),
        "payout_volume": _dec(payout_row[1]),
    }


async def recompute_day(session: AsyncSession, day: date) -> dict[str, Decimal]:
    """Idempotent upsert of the day's metric rows (values replaced, never incremented)."""
    metrics = await compute_daily_metrics(session, day)
    stmt = insert(DailyMetric).values(
        [{"day": day, "metric": name, "value": value} for name, value in metrics.items()]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyMetric.day, DailyMetric.metric],
        set_={"value": stmt.excluded.value, "updated_at": func.now()},
    )
    await session.execute(stmt)
    return metrics
