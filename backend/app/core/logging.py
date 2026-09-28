"""Structured application logging built on Logifyx.

Logifyx owns handlers, formatting (colored text or single-line JSON), rotation and masking. This module adds:

* ``get_logger(name)`` returning an :class:`AppLogger` that accepts structured fields:
  ``log.info("payment_confirmed", bounty_id=..., amount=...)``.
* Request-scoped context (request ID, correlation ID, user ID, service) held in a ContextVar and attached to
  every record — as JSON fields in JSON mode, or ``key=value`` pairs in text mode.
* Redaction of sensitive field names (passwords, tokens, secrets, keys, signed XDR) before anything reaches a
  handler, on top of Logifyx's own message masking.

Configuration comes from Settings (LOG_LEVEL, LOG_JSON, LOG_OUTPUT) and is applied once per process.
"""

from __future__ import annotations

import logging
import threading
from contextvars import ContextVar
from typing import Any

import logifyx

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "set-cookie",
        "secret",
        "private_key",
        "secret_key",
        "seed",
        "seed_phrase",
        "jwt_secret",
        "smtp_password",
        "signed_xdr",
        "signed_challenge_xdr",
        "x-csrf-token",
        "csrf_token",
    }
)

_context: ContextVar[dict[str, Any] | None] = ContextVar("bountyflow_log_context", default=None)
_configured = False
_lock = threading.Lock()


def configure_logging(
    level: str = "INFO", json_logs: bool = False, service: str = "api", output: str = "console"
) -> None:
    """Install the process-wide Logifyx policy. Containers log to stdout/stderr (output="console")."""
    global _configured
    with _lock:
        logifyx.configure_logging(
            level=level.upper(),
            output=output,
            json_mode=json_logs,
            color=not json_logs,
            mask=True,
        )
        # configure_logging registers Logifyx as the *global* logger class. Scope it to BountyFlow's own loggers
        # (created directly below) so third-party libraries keep standard hierarchical loggers and levels.
        logging.setLoggerClass(logging.Logger)
        _configured = True
    for noisy in ("aiokafka", "kafka", "sqlalchemy", "aiohttp", "uvicorn.access", "httpx", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    bind_context(service=service)


def _ensure_configured() -> None:
    if not _configured:
        configure_logging()


# --- Context ----------------------------------------------------------------------


def bind_context(**fields: Any) -> None:
    current = dict(_context.get() or {})
    current.update({k: v for k, v in fields.items() if v is not None})
    _context.set(current)


def unbind_context(*keys: str) -> None:
    current = dict(_context.get() or {})
    for key in keys:
        current.pop(key, None)
    _context.set(current)


def get_context() -> dict[str, Any]:
    return dict(_context.get() or {})


def clear_context() -> None:
    service = (_context.get() or {}).get("service")
    _context.set({"service": service} if service else {})


# --- Logger -----------------------------------------------------------------------


def _redact(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[REDACTED]" if k.lower() in _SENSITIVE_KEYS else v) for k, v in fields.items()}


class AppLogger:
    """Structured wrapper over a Logifyx logger (resolved lazily after configuration)."""

    __slots__ = ("_logger", "_name")

    def __init__(self, name: str) -> None:
        self._name = name if name.startswith("bountyflow") else f"bountyflow.{name}"
        self._logger: logging.Logger | None = None

    @property
    def logger(self) -> logging.Logger:
        if self._logger is None:
            _ensure_configured()
            self._logger = logifyx.Logifyx(self._name)
        return self._logger

    def _emit(self, level: int, event: str, exc_info: bool, fields: dict[str, Any]) -> None:
        logger = self.logger
        if not logger.isEnabledFor(level):
            return
        data = _redact({**get_context(), **fields})
        json_mode = bool(getattr(logger, "config", {}).get("json_mode"))
        if json_mode:
            extra = {"event": event, **{k: v for k, v in data.items() if k not in _RESERVED}}
            logger.log(level, event, exc_info=exc_info, extra=extra, stacklevel=4)
        else:
            pairs = " ".join(f"{k}={v}" for k, v in data.items())
            logger.log(level, f"{event} {pairs}" if pairs else event, exc_info=exc_info, stacklevel=4)

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, False, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, False, fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, False, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, False, fields)

    def exception(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, True, fields)

    def critical(self, event: str, **fields: Any) -> None:
        self._emit(logging.CRITICAL, event, False, fields)


# LogRecord attributes that must not be overwritten through `extra`.
_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

_loggers: dict[str, AppLogger] = {}


def get_logger(name: str | None = None) -> AppLogger:
    key = name or "app"
    if key not in _loggers:
        _loggers[key] = AppLogger(key)
    return _loggers[key]


def shutdown_logging() -> None:
    """Flush queued remote/Kafka log records on process exit."""
    try:
        logifyx.flush(timeout=3.0)
    except Exception:  # noqa: S110 - best effort during shutdown
        pass
