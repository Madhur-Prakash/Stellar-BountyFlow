"""ASGI middleware recording request counts and latency per route template (for ``/metrics``).

Routes are labelled by their template (``/api/v1/bounties/{bounty_ref}``), never the raw path, so label
cardinality stays bounded. Unmatched paths share the ``unmatched`` label.
"""

from __future__ import annotations

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.modules.ops.metrics import HTTP_EXCEPTIONS, HTTP_LATENCY, HTTP_REQUESTS

_SKIP = ("/metrics", "/health/live")


def _route(scope: Scope) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in _SKIP:
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        except Exception:
            HTTP_EXCEPTIONS.inc(_route(scope))
            status = 500
            raise
        finally:
            route = _route(scope)
            method = scope.get("method", "GET")
            HTTP_REQUESTS.inc(method, route, str(status))
            HTTP_LATENCY.observe(time.perf_counter() - started, method, route)
