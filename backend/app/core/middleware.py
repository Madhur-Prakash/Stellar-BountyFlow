"""ASGI middleware: request IDs + access logs, security headers, body-size limits, and CSRF double-submit."""

from __future__ import annotations

import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.logging import bind_context, get_logger, unbind_context
from app.core.security import CSRF_COOKIE, CSRF_HEADER, constant_time_equals, generate_token

logger = get_logger("http")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Accepted shape for client-supplied X-Request-ID / X-Correlation-ID values (UUIDs, hex, ULIDs...).
_TRACE_ID_RE = re.compile(r"[A-Za-z0-9._:-]{8,64}")

# Endpoints that establish a session or are protected by single-use tokens; they cannot carry a CSRF token yet.
CSRF_EXEMPT_SUFFIXES = (
    "/auth/register",
    "/auth/login",
    "/auth/refresh",
    "/auth/forgot-password",
    "/auth/reset-password",
    "/auth/verify-email",
    # Authorised by the signed token in the alert email (no session); it can only turn a search's alerts off.
    "/saved-searches/unsubscribe",
    # Server-to-server from GitHub, authenticated by the HMAC-SHA256 signature of every delivery (no cookies).
    "/github/webhook",
    # Public, cookie-free and side-effect free: checks a pasted credential (anyone may verify one).
    "/credentials/verify",
)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Security: client-supplied IDs end up in every log line, audit row and outbox event; accept only a
        # strict token shape so they cannot forge log fields (spaces, "key=value") or bloat events.
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _TRACE_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
        incoming_correlation = request.headers.get("x-correlation-id", "")
        correlation_id = incoming_correlation if _TRACE_ID_RE.fullmatch(incoming_correlation) else request_id
        request.state.request_id = request_id
        request.state.correlation_id = correlation_id
        bind_context(request_id=request_id, correlation_id=correlation_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            unbind_context("request_id", "correlation_id", "user_id")
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        if not request.url.path.startswith("/health"):
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                correlation_id=correlation_id,
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
        if get_settings().cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        if request.url.path.startswith(get_settings().api_prefix):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than the configured limit (checks Content-Length and streamed size)."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None:
            try:
                if int(length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={"error": {"code": "payload_too_large", "message": "Request body is too large."}},
        )
        await response(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection for cookie-authenticated mutating requests.

    Signing in mints the token (see ``app/modules/auth/router.py``). A visitor who has not signed in gets one
    from the first safe request they make, so the routes open to them — feedback — are protected by the same
    check as everything else rather than being exempted from it.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        path = request.url.path
        # Security: exempt routes are matched exactly (a suffix match would silently exempt any future route
        # whose path happens to end the same way), and every other mutating request is checked regardless of
        # its prefix.
        exempt = {settings.api_prefix + suffix for suffix in CSRF_EXEMPT_SUFFIXES}
        if request.method not in SAFE_METHODS and path not in exempt:
            cookie = request.cookies.get(CSRF_COOKIE)
            header = request.headers.get(CSRF_HEADER)
            if not cookie or not header or not constant_time_equals(cookie, header):
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "csrf_failed",
                            "message": "Missing or invalid CSRF token.",
                            "request_id": getattr(request.state, "request_id", None),
                        }
                    },
                )
        response = await call_next(request)
        if request.method in SAFE_METHODS:
            token = request.cookies.get(CSRF_COOKIE)
            if not token:
                token = generate_token(24)
                # Readable by JavaScript on purpose: the token must be echoed in the X-CSRF-Token header.
                response.set_cookie(
                    CSRF_COOKIE,
                    token,
                    max_age=settings.refresh_token_ttl,
                    httponly=False,
                    path="/",
                    secure=settings.cookie_secure,
                    samesite=settings.cookie_samesite,
                    domain=settings.cookie_domain,
                )
            # Also returned as a header, because a frontend served from another origin cannot read this
            # API's cookie out of document.cookie and would have nothing to submit back. CORS only lets
            # the configured origins read it (see `expose_headers`), so a third-party page still cannot.
            response.headers[CSRF_HEADER] = token
        return response
