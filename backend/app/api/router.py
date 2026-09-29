"""Top-level router: unversioned health endpoints plus the versioned API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.system import health_router
from app.api.v1.router import api_v1
from app.core.config import get_settings
from app.modules.credentials.router import well_known_router
from app.modules.ops.router import metrics_router


def build_router() -> APIRouter:
    root = APIRouter()
    root.include_router(health_router)
    root.include_router(metrics_router)
    root.include_router(well_known_router)
    root.include_router(api_v1, prefix=get_settings().api_prefix)
    return root
