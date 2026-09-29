"""Notification preference defaults, merging, and sparse updates."""

from __future__ import annotations

from app.modules.notifications import preferences as prefs
from app.modules.notifications.models import NotificationType


def test_defaults_enable_in_app_for_every_type() -> None:
    defaults = prefs.default_preferences()
    assert set(defaults) == {t.value for t in NotificationType}
    assert all(v["in_app"] for v in defaults.values())


def test_default_email_types_match_policy() -> None:
    defaults = prefs.default_preferences()
    emailed = {k for k, v in defaults.items() if v["email"]}
    assert emailed == {
        "APPLICATION_ACCEPTED",
        "SUBMISSION_APPROVED",
        "REVISION_REQUESTED",
        "PAYMENT_CONFIRMED",
        "DISPUTE_UPDATE",
        "SUBMISSION_RECEIVED",
        "APPLICATION_RECEIVED",
        "QUESTION_RECEIVED",
        "QUESTION_REPLY",
        "PULL_REQUEST_UPDATE",
        "CLAIM_AVAILABLE",
        "MILESTONE_PAID",
        "ARBITER_VOTE",
    }


def test_merge_applies_overrides_and_ignores_garbage() -> None:
    stored = {
        "PAYMENT_CONFIRMED": {"email": False},
        "SYSTEM": {"in_app": False, "email": "yes"},
        "NOT_A_TYPE": {"in_app": False},
        "BOUNTY_FUNDED": "invalid",
    }
    merged = prefs.merge_preferences(stored)
    assert merged["PAYMENT_CONFIRMED"] == {"in_app": True, "email": False}
    assert merged["SYSTEM"] == {"in_app": False, "email": False}
    assert "NOT_A_TYPE" not in merged
    assert merged["BOUNTY_FUNDED"] == {"in_app": True, "email": False}


def test_apply_update_stores_only_differences_from_defaults() -> None:
    stored = prefs.apply_update(
        {}, {"PAYMENT_CONFIRMED": {"email": False, "in_app": None}, "SYSTEM": {"email": True}}
    )
    assert stored == {"PAYMENT_CONFIRMED": {"email": False}, "SYSTEM": {"email": True}}
    # Reverting to the default removes the override entirely.
    assert prefs.apply_update(stored, {"PAYMENT_CONFIRMED": {"email": True}}) == {"SYSTEM": {"email": True}}


def test_allows_email_requires_global_switch_and_type() -> None:
    assert prefs.allows_email(True, None, NotificationType.PAYMENT_CONFIRMED)
    assert not prefs.allows_email(False, None, NotificationType.PAYMENT_CONFIRMED)
    assert not prefs.allows_email(True, None, NotificationType.BOUNTY_PUBLISHED)
    assert not prefs.allows_email(
        True, {"PAYMENT_CONFIRMED": {"email": False}}, NotificationType.PAYMENT_CONFIRMED
    )


def test_allows_in_app_respects_override() -> None:
    assert prefs.allows_in_app(None, NotificationType.SYSTEM)
    assert not prefs.allows_in_app({"SYSTEM": {"in_app": False}}, NotificationType.SYSTEM)
