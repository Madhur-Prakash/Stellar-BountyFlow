"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.router import build_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    CSRFMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.security import CSRF_HEADER
from app.lifespan import lifespan
from app.modules.ops.middleware import MetricsMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json, service="api", output=settings.log_output)
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        description=(
            "BountyFlow — a bounty marketplace with Soroban escrow on Stellar. "
            "Authentication uses HttpOnly cookies; mutating requests require the `X-CSRF-Token` header "
            "matching the `bf_csrf` cookie."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    # Middleware executes bottom-up for requests: the last added runs first.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", CSRF_HEADER, "X-Request-ID", "X-Correlation-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(MetricsMiddleware)  # outermost: measures the whole request
    app.include_router(build_router())
    return app


app = create_app()
