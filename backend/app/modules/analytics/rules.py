"""Metric definitions shared by the analytics API and the analytics worker.

Integrity rules applied everywhere:

* Every active account and every bounty counts, except bounties hidden by moderators.
* Only activity on the configured Stellar network counts; personal dashboards are scoped the same way.
* Blockchain metrics count each ``(network, transaction_hash)`` once, so resubmissions or retried
  verifications can never inflate totals. Only the configured network is counted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, or_, select

from app.modules.bounties.models import Bounty, BountyStatus
from app.modules.payments.models import BlockchainTransaction, PaymentRecord, TxStatus, TxType
from app.modules.users.models import User

PUBLIC_WINDOW = "All time, up to generated_at. Cached for at most 60 seconds."
SERIES_DAYS = 30
MONTHS = 12

# Marketplace statuses that count as "open" (visible and progressing), matching the default marketplace filter.
OPEN_STATUSES: tuple[BountyStatus, ...] = (
    BountyStatus.OPEN,
    BountyStatus.FUNDING_PENDING,
    BountyStatus.FUNDED,
    BountyStatus.IN_PROGRESS,
    BountyStatus.UNDER_REVIEW,
)

# Daily metric names maintained by the analytics worker (``daily_metrics.metric``).
DAILY_METRICS: tuple[str, ...] = (
    "registrations",
    "bounties_published",
    "bounties_funded",
    "bounties_completed",
    "applications",
    "submissions",
    "payouts_confirmed_count",
    "payout_volume",
)


# --- SQL predicates ------------------------------------------------------------------------


def active_user() -> ColumnElement[bool]:
    """Accounts that can currently sign in (suspended accounts drop out of live counts)."""
    return User.is_active.is_(True)


def visible_bounty() -> ColumnElement[bool]:
    """Bounties a moderator has not hidden."""
    return Bounty.is_hidden.is_(False)


def published_bounty() -> ColumnElement[bool]:
    return and_(visible_bounty(), Bounty.published_at.is_not(None), Bounty.status != BountyStatus.DRAFT)


def live_transaction(network: str) -> ColumnElement[bool]:
    """A verified, confirmed transaction on the configured network with a real hash."""
    return and_(
        BlockchainTransaction.status == TxStatus.CONFIRMED,
        BlockchainTransaction.network == network,
        BlockchainTransaction.transaction_hash.is_not(None),
        BlockchainTransaction.transaction_type != TxType.WALLET_CHALLENGE,
    )


def failed_transaction(network: str) -> ColumnElement[bool]:
    return and_(
        BlockchainTransaction.status.in_([TxStatus.FAILED, TxStatus.EXPIRED]),
        BlockchainTransaction.network == network,
        BlockchainTransaction.transaction_type != TxType.WALLET_CHALLENGE,
    )


def visible_bounty_tx() -> ColumnElement[bool]:
    """Transactions unrelated to a bounty, or related to a bounty moderators have not hidden (outer join)."""
    return or_(BlockchainTransaction.bounty_id.is_(None), Bounty.is_hidden.is_(False))


def network_payment(network: str) -> ColumnElement[bool]:
    """Payments for bounties on the configured network only."""
    return PaymentRecord.bounty_id.in_(select(Bounty.id).where(Bounty.network == network))


# --- Pure helpers ---------------------------------------------------------------------------


def rate(numerator: int | None, denominator: int | None) -> float | None:
    """A 0..1 ratio rounded to 4 decimals; None when there is nothing to divide by."""
    if not denominator:
        return None
    return round((numerator or 0) / denominator, 4)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def last_n_days(end: date, n: int = SERIES_DAYS) -> list[date]:
    return [end - timedelta(days=offset) for offset in range(n - 1, -1, -1)]


def month_key(value: date | datetime) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def last_n_months(end: date, n: int = MONTHS) -> list[str]:
    months: list[str] = []
    year, month = end.year, end.month
    for _ in range(n):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def fill_months(
    rows: Iterable[tuple[str, Decimal | None]], end: date, n: int = MONTHS
) -> list[dict[str, Any]]:
    """Dense monthly series (oldest first), zero-filled for months without data."""
    totals: dict[str, Decimal] = {}
    for month, amount in rows:
        totals[month] = totals.get(month, Decimal(0)) + Decimal(amount or 0)
    return [{"month": m, "amount": totals.get(m, Decimal(0))} for m in last_n_months(end, n)]


def zero_filled(keys: Iterable[str], counts: Mapping[str, int]) -> dict[str, int]:
    return {k: int(counts.get(k, 0)) for k in keys}


def public_methodology(network: str) -> dict[str, str]:
    env = f"On-chain metrics are verified against the Stellar {network} network."
    return {
        "time_window": PUBLIC_WINDOW,
        "environment": env,
        "registered_users": "Active accounts (suspended accounts are not counted).",
        "published_bounties": "Bounties ever published (not drafts), excluding bounties hidden by moderators.",
        "open_bounties": "Published bounties currently open or in progress (OPEN, FUNDING_PENDING, FUNDED, "
        "IN_PROGRESS, UNDER_REVIEW), excluding hidden bounties.",
        "funded_bounties": "Bounties whose escrow received funds, as recorded after on-chain verification.",
        "completed_bounties": "Bounties in COMPLETED status.",
        "verified_payout_volume": "Sum of confirmed PAYOUT transactions on this network, each "
        "transaction hash counted once. Denominated in XLM; other reward assets are listed separately.",
        "payout_volume_by_asset": "The same sum grouped per reward asset (XLM, USDC, ...). Amounts of different "
        "assets are never added together.",
        "successful_transactions": "Distinct confirmed transaction hashes on this network "
        "(wallet ownership challenges are never submitted and are excluded).",
        "unique_transacting_wallets": "Distinct source addresses of those confirmed transactions.",
    }


def platform_methodology(network: str) -> dict[str, str]:
    return {
        **public_methodology(network),
        "time_window": "Totals are all time up to generated_at; active_users uses the last 30 days; "
        f"time_series covers the last {SERIES_DAYS} UTC days.",
        "verified_users": "Active accounts with a verified email address.",
        "connected_wallets": "Distinct users with at least one verified wallet on this network.",
        "active_users_30d": "Accounts that logged in within the last 30 days.",
        "failed_transactions": "Distinct transactions on this network that FAILED or EXPIRED.",
        "repeat_contributors": "Contributors with two or more completed assignments.",
        "application_acceptance_rate": "Accepted / (accepted + rejected) applications.",
        "submission_approval_rate": "Approved / (approved + rejected) submissions.",
        "time_series": "Daily values recomputed idempotently from source tables by the analytics worker "
        "(UTC days), counting confirmed transactions on this network only.",
    }
