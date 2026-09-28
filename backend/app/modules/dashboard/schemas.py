"""Dashboard response schema."""

from __future__ import annotations

from app.core.schemas import APIModel
from app.modules.bounties.schemas import ActivityItem, BountySummary


class Dashboard(APIModel):
    active_bounties: int
    pending_applications_to_review: int
    submissions_awaiting_review: int
    pending_payments: int
    my_pending_applications: int
    my_active_assignments: int
    revision_requests: int
    recent_completed: list[BountySummary]
    recent_activity: list[ActivityItem]
    recommendations: list[BountySummary]
