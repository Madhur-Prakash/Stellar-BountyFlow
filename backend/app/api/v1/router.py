"""Version 1 API router: mounts every domain module."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.system import config_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.router_users import router as admin_users_router
from app.modules.analytics.router import router as analytics_router
from app.modules.applications.router import router as applications_router
from app.modules.assets.router import router as assets_router
from app.modules.auth.router import router as auth_router
from app.modules.bounties.router import router as bounties_router
from app.modules.compliance.router import router as compliance_router
from app.modules.compliance.router_admin import router as admin_compliance_router
from app.modules.credentials.router import router as credentials_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.discovery.router import router as discovery_router
from app.modules.disputes.router import router as disputes_router
from app.modules.escrow.router import router as escrow_router
from app.modules.feedback.router import admin_router as admin_feedback_router
from app.modules.feedback.router import router as feedback_router
from app.modules.github.router import router as github_router
from app.modules.notifications.router import router as notifications_router
from app.modules.ops.router import router as admin_ops_router
from app.modules.payments.router import router as payments_router
from app.modules.qa.router import admin_router as admin_qa_router
from app.modules.qa.router import router as qa_router
from app.modules.reputation.router import router as reputation_router
from app.modules.submissions.router import router as submissions_router
from app.modules.users.router import router as users_router
from app.modules.wallets.router import admin_router as admin_wallets_router
from app.modules.wallets.router import router as wallets_router

api_v1 = APIRouter()
for router in (
    config_router,
    auth_router,
    users_router,
    wallets_router,
    bounties_router,
    applications_router,
    submissions_router,
    qa_router,
    github_router,
    payments_router,
    assets_router,
    disputes_router,
    escrow_router,
    feedback_router,
    notifications_router,
    compliance_router,
    analytics_router,
    dashboard_router,
    discovery_router,
    reputation_router,
    credentials_router,
    admin_users_router,
    admin_compliance_router,
    admin_feedback_router,
    admin_ops_router,
    admin_qa_router,
    admin_wallets_router,
    admin_router,
):
    api_v1.include_router(router)
