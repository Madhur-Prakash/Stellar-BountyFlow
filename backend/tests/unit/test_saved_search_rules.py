"""Saved-search filters, digest scheduling and signed unsubscribe tokens (no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.modules.bounties.models import Category
from app.modules.discovery.models import AlertFrequency
from app.modules.discovery.saved_searches import next_digest_time
from app.modules.discovery.schemas import SavedSearchCreate, SavedSearchFilters
from app.modules.discovery.tokens import make_unsubscribe_token, read_unsubscribe_token

SECRET = "unit-test-secret-" + "x" * 32
NOW = datetime(2026, 9, 29, 12, 30, tzinfo=UTC)  # a Tuesday


def test_filters_keep_the_deadline_as_a_rolling_window() -> None:
    saved = SavedSearchFilters(
        q=" soroban ", skills=["Rust", "rust"], funded_only=True, deadline_within_days=7
    )
    assert saved.q == "soroban" and saved.skills == ["rust"]
    market = saved.to_marketplace(NOW)
    assert market.deadline_after == NOW and market.deadline_before == NOW + timedelta(days=7)
    assert market.funded_only is True and market.skills == ["rust"]
    later = saved.to_marketplace(NOW + timedelta(days=30))
    assert later.deadline_before == NOW + timedelta(days=37)  # never goes stale


def test_filters_refuse_fixed_deadlines() -> None:
    with pytest.raises(ValidationError):
        SavedSearchFilters(deadline_before=NOW)


def test_stored_filters_load_tolerantly() -> None:
    stored = SavedSearchFilters(category=[Category.SECURITY], q="audit").stored()
    assert SavedSearchFilters.from_stored(stored).category == [Category.SECURITY]
    broken = {**stored, "category": ["NOT_A_CATEGORY"], "min_reward": "-3"}
    loaded = SavedSearchFilters.from_stored(broken)
    assert loaded.q == "audit" and loaded.category is None and loaded.min_reward is None


def test_saved_search_names_are_trimmed_and_required() -> None:
    assert SavedSearchCreate(name="  Rust   work ").name == "Rust work"
    with pytest.raises(ValidationError):
        SavedSearchCreate(name="    ")


def test_daily_digests_go_out_at_the_configured_hour() -> None:
    assert next_digest_time(AlertFrequency.DAILY, NOW, hour=8) == datetime(2026, 9, 30, 8, tzinfo=UTC)
    assert next_digest_time(AlertFrequency.DAILY, NOW.replace(hour=7), hour=8) == NOW.replace(
        hour=8, minute=0
    )


def test_weekly_digests_go_out_on_mondays() -> None:
    assert next_digest_time(AlertFrequency.WEEKLY, NOW, hour=8) == datetime(2026, 10, 5, 8, tzinfo=UTC)
    monday_early = datetime(2026, 10, 5, 6, tzinfo=UTC)
    assert next_digest_time(AlertFrequency.WEEKLY, monday_early, hour=8) == datetime(
        2026, 10, 5, 8, tzinfo=UTC
    )
    monday_late = datetime(2026, 10, 5, 9, tzinfo=UTC)
    assert next_digest_time(AlertFrequency.WEEKLY, monday_late, hour=8) == datetime(
        2026, 10, 12, 8, tzinfo=UTC
    )


def test_instant_and_off_have_no_digest() -> None:
    assert next_digest_time(AlertFrequency.INSTANT, NOW, hour=8) is None
    assert next_digest_time(AlertFrequency.OFF, NOW, hour=8) is None


def test_unsubscribe_tokens_verify_only_untampered() -> None:
    search, user = uuid.uuid4(), uuid.uuid4()
    token = make_unsubscribe_token(search, user, SECRET)
    claims = read_unsubscribe_token(token, SECRET)
    assert claims is not None and claims.saved_search_id == search and claims.user_id == user

    other = uuid.uuid4()
    forged = token.replace(search.hex, other.hex)
    assert read_unsubscribe_token(forged, SECRET) is None
    assert read_unsubscribe_token(token, SECRET + "-rotated") is None
    assert read_unsubscribe_token(token[:-2], SECRET) is None
    assert read_unsubscribe_token("v1.not.a.token", SECRET) is None
    assert read_unsubscribe_token("", SECRET) is None
