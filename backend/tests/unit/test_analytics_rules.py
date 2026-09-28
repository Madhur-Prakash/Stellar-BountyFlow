"""Analytics definitions: exclusion rules, ratios, dense time series, and methodology coverage."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.dialects import postgresql

from app.modules.analytics import rules
from app.modules.analytics.schemas import PublicStats
from app.modules.analytics.service import build_daily_point


def sql(clause: object) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]


def test_live_transactions_exclude_unconfirmed_other_networks_and_challenges() -> None:
    text = sql(rules.live_transaction("testnet"))
    assert "blockchain_transactions.status = 'CONFIRMED'" in text
    assert "blockchain_transactions.network = 'testnet'" in text
    assert "blockchain_transactions.transaction_hash IS NOT NULL" in text
    assert "blockchain_transactions.transaction_type != 'WALLET_CHALLENGE'" in text


def test_suspended_accounts_and_hidden_bounties_are_excluded() -> None:
    assert "users.is_active IS true" in sql(rules.active_user())
    bounty = sql(rules.published_bounty())
    assert "bounties.is_hidden IS false" in bounty
    assert "bounties.published_at IS NOT NULL" in bounty
    assert "bounties.status != 'DRAFT'" in bounty


def test_network_payment_filter_is_scoped_to_the_configured_network() -> None:
    text = " ".join(sql(rules.network_payment("testnet")).split())
    assert (
        "payment_records.bounty_id IN (SELECT bounties.id FROM bounties WHERE bounties.network = 'testnet')"
        in text
    )
    assert "'mainnet'" in sql(rules.network_payment("mainnet"))


def test_rate() -> None:
    assert rules.rate(1, 3) == 0.3333
    assert rules.rate(0, 5) == 0.0
    assert rules.rate(3, 0) is None
    assert rules.rate(None, None) is None


def test_last_n_months_crosses_year_boundary() -> None:
    assert rules.last_n_months(date(2026, 2, 10), 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_fill_months_zero_fills_and_sums() -> None:
    series = rules.fill_months(
        [("2026-01", Decimal("5.5")), ("2026-01", Decimal("1")), ("2025-12", None)], date(2026, 2, 1), 3
    )
    assert series == [
        {"month": "2025-12", "amount": Decimal(0)},
        {"month": "2026-01", "amount": Decimal("6.5")},
        {"month": "2026-02", "amount": Decimal(0)},
    ]


def test_day_bounds_are_utc_half_open() -> None:
    start, end = rules.day_bounds(date(2026, 9, 25))
    assert start == datetime(2026, 9, 25, tzinfo=UTC)
    assert end == datetime(2026, 9, 26, tzinfo=UTC)


def test_last_n_days_is_oldest_first_and_inclusive() -> None:
    days = rules.last_n_days(date(2026, 9, 25), 3)
    assert days == [date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 25)]


def test_public_methodology_documents_every_metric_and_window() -> None:
    methodology = rules.public_methodology("testnet")
    numeric_fields = {
        name
        for name, field in PublicStats.model_fields.items()
        if name not in {"network", "generated_at", "methodology"}
    }
    assert numeric_fields <= set(methodology)
    assert "time_window" in methodology
    assert "counted once" in methodology["verified_payout_volume"]


def test_environment_names_the_verified_network() -> None:
    assert "Stellar testnet network" in rules.public_methodology("testnet")["environment"]
    assert "Stellar mainnet network" in rules.public_methodology("mainnet")["environment"]
    platform = rules.platform_methodology("testnet")
    assert platform["environment"] == rules.public_methodology("testnet")["environment"]
    assert "time_series" in platform
    assert "30" in platform["time_window"]


def test_daily_point_defaults_missing_metrics_to_zero_and_serializes_money() -> None:
    point = build_daily_point(
        date(2026, 9, 25), {"registrations": Decimal(3), "payout_volume": Decimal("12.5")}
    )
    assert point.registrations == 3
    assert point.submissions == 0
    dumped = point.model_dump(mode="json")
    assert dumped["payout_volume"] == "12.5000000"
    assert set(rules.DAILY_METRICS) <= set(dumped)
