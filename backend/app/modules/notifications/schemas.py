"""Notification API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.schemas import APIModel, Page
from app.modules.notifications.models import NotificationType


class NotificationOut(APIModel):
    id: uuid.UUID
    notification_type: NotificationType
    title: str
    message: str
    payload: dict[str, Any]
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationPage(Page[NotificationOut]):
    unread_count: int


class TypePreference(APIModel):
    in_app: bool
    email: bool


class TypePreferenceUpdate(APIModel):
    in_app: bool | None = None
    email: bool | None = None


class NotificationPreferencesOut(APIModel):
    email_enabled: bool
    types: dict[NotificationType, TypePreference]


class NotificationPreferencesUpdate(APIModel):
    email_enabled: bool | None = None
    types: dict[NotificationType, TypePreferenceUpdate] | None = None
