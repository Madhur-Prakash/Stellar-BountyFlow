"""Version 1 API router: mounts every domain module."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.system import config_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.router_users import router as admin_users_router
from app.modules.analytics.router import router as analytics_router
from app.modules.applications.router import router as applications_router
from app.modules.auth.router import router as auth_router
from app.modules.bounties.router import router as bounties_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.disputes.router import router as disputes_router
from app.modules.notifications.router import router as notifications_router
from app.modules.payments.router import router as payments_router
from app.modules.submissions.router import router as submissions_router
from app.modules.users.router import router as users_router

api_v1 = APIRouter()
for router in (
    config_router,
    auth_router,
    users_router,
    bounties_router,
    applications_router,
    submissions_router,
    payments_router,
    disputes_router,
    notifications_router,
    analytics_router,
    dashboard_router,
    admin_users_router,
    admin_router,
):
    api_v1.include_router(router)
