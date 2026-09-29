"""Notification preference defaults and merging (pure functions, no I/O).

Stored preferences are sparse: ``NotificationPreference.types`` only holds the values a user changed. Every
read merges them over the defaults, so adding a new notification type never requires a data migration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.notifications.models import NotificationType

CHANNELS: tuple[str, ...] = ("in_app", "email")

# Types that email by default: things a user must act on, or confirmations of money movement.
DEFAULT_EMAIL_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.APPLICATION_ACCEPTED,
        NotificationType.SUBMISSION_APPROVED,
        NotificationType.REVISION_REQUESTED,
        NotificationType.PAYMENT_CONFIRMED,
        NotificationType.DISPUTE_UPDATE,
        NotificationType.SUBMISSION_RECEIVED,
        NotificationType.APPLICATION_RECEIVED,
        NotificationType.QUESTION_RECEIVED,
        NotificationType.QUESTION_REPLY,
        NotificationType.PULL_REQUEST_UPDATE,
        NotificationType.CLAIM_AVAILABLE,
        NotificationType.MILESTONE_PAID,
        NotificationType.ARBITER_VOTE,
    }
)

DEFAULT_EMAIL_ENABLED = True

TypePrefs = dict[str, bool]


def default_type_prefs(notification_type: NotificationType) -> TypePrefs:
    return {"in_app": True, "email": notification_type in DEFAULT_EMAIL_TYPES}


def default_preferences() -> dict[str, TypePrefs]:
    return {t.value: default_type_prefs(t) for t in NotificationType}


def merge_preferences(stored: Mapping[str, Any] | None) -> dict[str, TypePrefs]:
    """Effective per-type preferences: stored overrides applied over the defaults. Unknown types and
    malformed values in storage are ignored."""
    merged = default_preferences()
    for key, value in (stored or {}).items():
        if key not in merged or not isinstance(value, Mapping):
            continue
        for channel in CHANNELS:
            if isinstance(value.get(channel), bool):
                merged[key][channel] = value[channel]
    return merged


def apply_update(
    stored: Mapping[str, Any] | None, changes: Mapping[str, Mapping[str, bool | None]]
) -> dict[str, TypePrefs]:
    """Return the new sparse storage value after a partial update. Only values that differ from the default
    are kept, so storage stays minimal and future default changes still apply to untouched settings."""
    effective = merge_preferences(stored)
    for key, channels in changes.items():
        if key not in effective:
            continue
        for channel in CHANNELS:
            value = channels.get(channel)
            if value is not None:
                effective[key][channel] = value
    sparse: dict[str, TypePrefs] = {}
    for t in NotificationType:
        default = default_type_prefs(t)
        diff = {ch: effective[t.value][ch] for ch in CHANNELS if effective[t.value][ch] != default[ch]}
        if diff:
            sparse[t.value] = diff
    return sparse


def allows_in_app(stored: Mapping[str, Any] | None, notification_type: NotificationType) -> bool:
    return merge_preferences(stored)[notification_type.value]["in_app"]


def allows_email(
    email_enabled: bool, stored: Mapping[str, Any] | None, notification_type: NotificationType
) -> bool:
    return email_enabled and merge_preferences(stored)[notification_type.value]["email"]
