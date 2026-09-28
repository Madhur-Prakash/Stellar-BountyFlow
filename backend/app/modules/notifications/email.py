"""Email rendering (Jinja2, autoescaped) and delivery backends (SMTP via aiosmtplib, or console).

Rendered bodies may contain single-use tokens inside links. They are handed straight to the backend and are
never logged or persisted: logs carry only the template name, subject, and recipient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.modules.notifications.models import NotificationType

logger = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "email"

VERIFY_EMAIL = "verify_email"
PASSWORD_RESET = "password_reset"
NOTIFICATION = "notification"

# Frontend route for notification settings (linked from every notification email footer).
PREFERENCES_PATH = "/app/settings"


class EmailSendError(Exception):
    """Transient delivery failure; the worker retries the event."""


@dataclass(frozen=True)
class RenderedEmail:
    template: str
    subject: str
    html: str
    text: str


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    html: str
    text: str
    headers: dict[str, str] = field(default_factory=dict)


# --- Rendering -------------------------------------------------------------------------


@lru_cache
def get_template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
        keep_trailing_newline=True,
    )


def frontend_url(path: str, query: dict[str, str] | None = None, settings: Settings | None = None) -> str:
    base = (settings or get_settings()).frontend_url.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    return f"{url}?{urlencode(query)}" if query else url


def _duration(seconds: int) -> str:
    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    minutes = max(1, seconds // 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def render(
    template: str, subject: str, context: dict[str, Any], settings: Settings | None = None
) -> RenderedEmail:
    settings = settings or get_settings()
    env = get_template_env()
    full_context: dict[str, Any] = {
        "subject": subject,
        "app_name": settings.app_name,
        "year": datetime.now(UTC).year,
        "recipient_name": None,
        "action_url": None,
        "action_label": "Open BountyFlow",
        "preferences_url": None,
        **context,
    }
    html = env.get_template(f"{template}.html").render(full_context)
    text = env.get_template(f"{template}.txt").render(full_context)
    return RenderedEmail(template=template, subject=subject, html=html, text=text)


def render_verify_email(
    recipient_name: str, raw_token: str, settings: Settings | None = None
) -> RenderedEmail:
    settings = settings or get_settings()
    return render(
        VERIFY_EMAIL,
        f"Confirm your email for {settings.app_name}",
        {
            "recipient_name": recipient_name,
            "action_url": frontend_url("/verify-email", {"token": raw_token}, settings),
            "action_label": "Confirm email address",
            "expires_in": _duration(settings.email_verification_ttl),
        },
        settings,
    )


def render_password_reset(
    recipient_name: str, raw_token: str, settings: Settings | None = None
) -> RenderedEmail:
    settings = settings or get_settings()
    return render(
        PASSWORD_RESET,
        f"Reset your {settings.app_name} password",
        {
            "recipient_name": recipient_name,
            "action_url": frontend_url("/reset-password", {"token": raw_token}, settings),
            "action_label": "Choose a new password",
            "expires_in": _duration(settings.password_reset_ttl),
        },
        settings,
    )


_CATEGORY_LABELS = {
    NotificationType.PAYMENT_CONFIRMED: "Payment",
    NotificationType.BOUNTY_FUNDED: "Escrow",
    NotificationType.DISPUTE_UPDATE: "Dispute",
    NotificationType.APPLICATION_RECEIVED: "Application",
    NotificationType.APPLICATION_ACCEPTED: "Application",
    NotificationType.APPLICATION_REJECTED: "Application",
    NotificationType.SUBMISSION_RECEIVED: "Submission",
    NotificationType.REVISION_REQUESTED: "Submission",
    NotificationType.SUBMISSION_APPROVED: "Submission",
    NotificationType.SUBMISSION_REJECTED: "Submission",
}

_ACTION_LABELS = {
    NotificationType.PAYMENT_CONFIRMED: "View payment",
    NotificationType.APPLICATION_RECEIVED: "Review applications",
    NotificationType.SUBMISSION_RECEIVED: "Review submission",
    NotificationType.REVISION_REQUESTED: "View feedback",
    NotificationType.DISPUTE_UPDATE: "View dispute",
}


def _format_amount(value: Any) -> str:
    raw = str(value)
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    return f"{raw} XLM"


def render_notification(
    *,
    recipient_name: str,
    notification_type: NotificationType,
    title: str,
    message: str,
    link: str | None,
    payload: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> RenderedEmail:
    settings = settings or get_settings()
    payload = payload or {}
    details: list[tuple[str, str]] = []
    if payload.get("amount") is not None:
        details.append(("Amount", _format_amount(payload["amount"])))
    if notification_type == NotificationType.PAYMENT_CONFIRMED:
        details.append(("Network", f"Stellar {settings.network_label.title()}"))
    return render(
        NOTIFICATION,
        f"{title} | {settings.app_name}",
        {
            "recipient_name": recipient_name,
            "title": title,
            "message": message,
            "details": details,
            "category_label": _CATEGORY_LABELS.get(notification_type, "Update"),
            "action_url": frontend_url(link, settings=settings) if link else None,
            "action_label": _ACTION_LABELS.get(notification_type, "Open in BountyFlow"),
            "preferences_url": frontend_url(PREFERENCES_PATH, settings=settings),
        },
        settings,
    )


# --- Delivery ----------------------------------------------------------------------------


class EmailBackend(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


def build_mime(message: OutgoingEmail, sender: str) -> EmailMessage:
    mime = EmailMessage()
    mime["From"] = sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].rstrip(">") or None)
    for key, value in message.headers.items():
        mime[key] = value
    mime.set_content(message.text)
    mime.add_alternative(message.html, subtype="html")
    return mime


class SmtpEmailBackend:
    def __init__(self, settings: Settings | None = None, timeout: float = 15.0) -> None:
        self.settings = settings or get_settings()
        self.timeout = timeout

    async def send(self, message: OutgoingEmail) -> None:
        s = self.settings
        try:
            await aiosmtplib.send(
                build_mime(message, s.email_from),
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_username or None,
                password=s.smtp_password or None,
                start_tls=s.smtp_use_tls,
                use_tls=False,
                timeout=self.timeout,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise EmailSendError(f"SMTP delivery failed: {type(exc).__name__}") from exc
        logger.info("email_sent", backend="smtp", to=message.to, subject=message.subject)


class ConsoleEmailBackend:
    """Development backend: records that an email would be sent. Bodies (which may hold tokens) are never
    written to the log."""

    async def send(self, message: OutgoingEmail) -> None:
        logger.info("email_sent", backend="console", to=message.to, subject=message.subject)


_backend: EmailBackend | None = None


def get_email_backend() -> EmailBackend:
    global _backend
    if _backend is None:
        settings = get_settings()
        _backend = SmtpEmailBackend(settings) if settings.email_backend == "smtp" else ConsoleEmailBackend()
    return _backend


def set_email_backend(backend: EmailBackend | None) -> None:
    """Used by tests to capture outgoing mail."""
    global _backend
    _backend = backend
