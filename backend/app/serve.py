"""Cross-platform API server entry point: ``python -m app.serve``.

Equivalent to ``uvicorn app.main:app`` but runs on a selector event loop on Windows (required by psycopg's async
driver). Containers and Linux/macOS hosts can use plain uvicorn as well.
"""

from __future__ import annotations

import os

import uvicorn

from app.core.config import get_settings
from app.core.runtime import run_async


def run() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        "app.main:app",
        host=os.environ.get(
            "API_BIND_HOST", "127.0.0.1" if settings.app_env == "development" else settings.api_host
        ),
        port=settings.api_port,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=15,
    )
    run_async(uvicorn.Server(config).serve())


if __name__ == "__main__":
    run()
