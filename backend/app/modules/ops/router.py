"""``GET /metrics`` (Prometheus) and the staff operations snapshot used by the runbooks.

``/metrics`` is served at the origin root, outside ``/api/v1`` and the OpenAPI document. It answers only:

* requests with ``Authorization: Bearer <METRICS_TOKEN>`` when a token is configured, or
* when no token is configured, direct loopback requests (no ``X-Forwarded-For``), so the bundled nginx, which
  only proxies ``/api`` and ``/health``, can never expose it.

Anything else gets 404, so the endpoint does not advertise itself.
"""

from __future__ import annotations

import ipaddress
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import get_settings
from app.core.rbac import Permission
from app.core.schemas import APIModel
from app.core.security import constant_time_equals
from app.dependencies import require_permission
from app.modules.ops import collectors, health
from app.modules.ops.metrics import REQUEST_METRICS, render
from app.modules.users.models import User

metrics_router = APIRouter(include_in_schema=False)
router = APIRouter(prefix="/admin/ops", tags=["admin"])

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _loopback(request: Request) -> bool:
    if request.headers.get("x-forwarded-for") or not request.client:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def authorised(request: Request) -> bool:
    settings = get_settings()
    if not settings.metrics_enabled:
        return False
    if settings.metrics_token:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        return (
            scheme.lower() == "bearer" and bool(token) and constant_time_equals(token, settings.metrics_token)
        )
    return _loopback(request)


@metrics_router.get("/metrics")
async def metrics(request: Request) -> Response:
    if not authorised(request):
        raise StarletteHTTPException(status_code=404, detail="Not Found")
    started = time.perf_counter()
    families = [*REQUEST_METRICS, *await collectors.collect()]
    body = render(families)
    body += (
        "# HELP bountyflow_metrics_scrape_duration_seconds Time spent collecting this scrape.\n"
        "# TYPE bountyflow_metrics_scrape_duration_seconds gauge\n"
        f"bountyflow_metrics_scrape_duration_seconds {time.perf_counter() - started:.4f}\n"
    )
    return Response(content=body, media_type=CONTENT_TYPE, headers={"Cache-Control": "no-store"})


class OpsStatus(APIModel):
    jobs: dict[str, dict[str, Any]]
    workers: dict[str, float]
    kafka_lag: dict[str, dict[str, Any]]
    reconciliation: dict[str, Any] | None


@router.get("/status", response_model=OpsStatus)
async def ops_status(
    user: Annotated[User, Depends(require_permission(Permission.SYSTEM_HEALTH))],
) -> OpsStatus:
    """Worker job health, heartbeats, consumer lag and the last reconciliation audit (see docs/runbooks)."""
    return OpsStatus(
        jobs=await health.job_health(),
        workers=await health.worker_heartbeats(),
        kafka_lag=await health.consumer_lag(),
        reconciliation=await health.reconciliation(),
    )
