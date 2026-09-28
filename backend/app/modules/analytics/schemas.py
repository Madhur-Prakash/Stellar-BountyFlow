"""Analytics API schemas. Money is serialized as fixed 7-decimal strings."""

from __future__ import annotations

from datetime import date, datetime

from app.core.schemas import APIModel, Money


class PublicStats(APIModel):
    network: str
    generated_at: datetime
    registered_users: int
    published_bounties: int
    open_bounties: int
    funded_bounties: int
    completed_bounties: int
    verified_payout_volume: Money
    successful_transactions: int
    unique_transacting_wallets: int
    methodology: dict[str, str]


class MonthlyAmount(APIModel):
    month: str  # YYYY-MM
    amount: Money


class RequesterAnalytics(APIModel):
    bounties_by_status: dict[str, int]
    total_escrowed: Money
    total_paid: Money
    applications_received: int
    avg_time_to_first_application_hours: float | None
    spending_by_month: list[MonthlyAmount]


class ContributorAnalytics(APIModel):
    applications_by_status: dict[str, int]
    submissions_by_status: dict[str, int]
    total_earned: Money
    earnings_by_month: list[MonthlyAmount]
    completed_count: int


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
    verified_payout_volume: Money


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
    payout_volume: Money


class PlatformAnalytics(APIModel):
    network: str
    generated_at: datetime
    users: PlatformUsers
    bounties: PlatformBounties
    transactions: PlatformTransactions
    engagement: PlatformEngagement
    time_series: list[DailyPoint]
    methodology: dict[str, str]
