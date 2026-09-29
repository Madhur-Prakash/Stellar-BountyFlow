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
    """The served route template, e.g. ``/api/v1/bounties/{bounty_ref}``.

    ``scope["route"]`` is the route as it was declared on its own router (``/bounties/{bounty_ref}``): FastAPI
    keeps an included router nested instead of flattening it, so the prefixes it was included under
    (``/api/v1``) live only in the request path. Those prefixes are literal and add no path parameters, so the
    template covers the last segments of the path and whatever leads them is the prefix."""
    route = scope.get("route")
    template = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not isinstance(template, str) or not template:
        return "unmatched"
    path = scope.get("path") or ""
    root_path = scope.get("root_path") or ""  # a proxy mount is deployment detail, not part of the route
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :]
    segments = path.split("/")
    depth = len(segments) - len(template.split("/"))
    return "/".join(segments[: depth + 1]) + template if depth > 0 else template


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
