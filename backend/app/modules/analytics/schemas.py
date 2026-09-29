"""Analytics API schemas. Money is serialized as fixed 7-decimal strings.

Amounts of different assets are never added together. The scalar money fields are XLM only (as before USDC and other
reward assets existed); every total also has a ``*_by_asset`` breakdown with one entry per asset."""

from __future__ import annotations

from datetime import date, datetime

from app.core.schemas import APIModel, Asset, AssetAmount, Money


class PublicStats(APIModel):
    network: str
    generated_at: datetime
    registered_users: int
    published_bounties: int
    open_bounties: int
    funded_bounties: int
    completed_bounties: int
    verified_payout_volume: Money  # XLM only
    payout_volume_by_asset: list[AssetAmount] = []
    successful_transactions: int
    unique_transacting_wallets: int
    methodology: dict[str, str]


class MonthlyAmount(APIModel):
    month: str  # YYYY-MM
    amount: Money


class AssetSeries(APIModel):
    """One asset's total and its dense monthly series (oldest first)."""

    asset: Asset
    total: Money
    months: list[MonthlyAmount]


class RequesterAnalytics(APIModel):
    bounties_by_status: dict[str, int]
    total_escrowed: Money  # XLM only
    total_paid: Money  # XLM only
    applications_received: int
    avg_time_to_first_application_hours: float | None
    spending_by_month: list[MonthlyAmount]  # XLM only
    escrowed_by_asset: list[AssetAmount] = []
    paid_by_asset: list[AssetAmount] = []
    spending_by_asset: list[AssetSeries] = []


class ContributorAnalytics(APIModel):
    applications_by_status: dict[str, int]
    submissions_by_status: dict[str, int]
    total_earned: Money  # XLM only
    earnings_by_month: list[MonthlyAmount]  # XLM only
    completed_count: int
    earned_by_asset: list[AssetAmount] = []
    earnings_by_asset: list[AssetSeries] = []


class MyAnalytics(APIModel):
    requester: RequesterAnalytics
    contributor: ContributorAnalytics


class PlatformUsers(APIModel):
    registered_users: int
    verified_users: int
    connected_wallets: int
    active_users_30d: int
    email_verification_rate: float | None
    wallet_connection_rate: float | None


class PlatformBounties(APIModel):
    published_bounties: int
    open_bounties: int
    funded_bounties: int
    completed_bounties: int


class PlatformTransactions(APIModel):
    unique_transacting_wallets: int
    successful_transactions: int
    failed_transactions: int
    verified_payout_volume: Money  # XLM only
    payout_volume_by_asset: list[AssetAmount] = []


class PlatformEngagement(APIModel):
    repeat_contributors: int
    applications_decided: int
    application_acceptance_rate: float | None
    submissions_reviewed: int
    submission_approval_rate: float | None


class DailyPoint(APIModel):
    day: date
    registrations: int
    bounties_published: int
    bounties_funded: int
    bounties_completed: int
    applications: int
    submissions: int
    payouts_confirmed_count: int
    payout_volume: Money  # XLM only
    payout_volume_by_asset: dict[str, Money] = {}  # asset identifier -> volume (every asset, XLM included)


class PlatformAnalytics(APIModel):
    network: str
    generated_at: datetime
    users: PlatformUsers
    bounties: PlatformBounties
    transactions: PlatformTransactions
    engagement: PlatformEngagement
    time_series: list[DailyPoint]
    methodology: dict[str, str]
