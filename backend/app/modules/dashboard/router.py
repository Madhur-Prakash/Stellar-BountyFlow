"""Dashboard endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import CurrentUser, SessionDep
from app.modules.dashboard import service
from app.modules.dashboard.schemas import Dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=Dashboard)
async def dashboard(session: SessionDep, user: CurrentUser) -> Dashboard:
    return await service.build(session, user)
