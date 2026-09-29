"""Email rendering (Jinja2, autoescaped) and delivery backends (Gmail API, SMTP, or console).

Rendered bodies may contain single-use tokens inside links. They are handed straight to the backend and are
never logged or persisted: logs carry only the template name, subject, and recipient.

**Transports.** SMTP (aiosmtplib) is the development path and points at Mailpit. The Gmail API transport is
what a deployment uses, and takes over as soon as ``GMAIL_CREDENTIALS_B64`` is set — Google refuses plain
passwords, and an app password needs 2FA plus a per-account secret a Workspace admin can switch off, whereas a
refresh token scoped to ``gmail.send`` grants exactly one capability. ``ConsoleEmailBackend`` records that a
message would have been sent and is what explicit ``EMAIL_BACKEND=console`` selects.

Every failure reaches the caller as :class:`EmailSendError`, which is what makes the worker retry the event.
The Gmail backend rides out a blip itself before giving up, and says in the error whether the cause looks
transient or permanent so a dead credential is not mistaken for a network wobble.
"""

from __future__ import annotations

import asyncio
import base64
import pickle
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import make_msgid
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import urlencode

import aiosmtplib
import anyio.to_thread
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
    NotificationType.QUESTION_RECEIVED: "Question",
    NotificationType.QUESTION_REPLY: "Question",
    NotificationType.ANSWER_ACCEPTED: "Question",
    NotificationType.PULL_REQUEST_UPDATE: "Pull request",
    NotificationType.CLAIM_AVAILABLE: "Payment",
    NotificationType.MILESTONE_PAID: "Payment",
    NotificationType.ARBITER_VOTE: "Dispute",
}

_ACTION_LABELS = {
    NotificationType.PAYMENT_CONFIRMED: "View payment",
    NotificationType.APPLICATION_RECEIVED: "Review applications",
    NotificationType.SUBMISSION_RECEIVED: "Review submission",
    NotificationType.REVISION_REQUESTED: "View feedback",
    NotificationType.DISPUTE_UPDATE: "View dispute",
    NotificationType.QUESTION_RECEIVED: "View question",
    NotificationType.QUESTION_REPLY: "View thread",
    NotificationType.PULL_REQUEST_UPDATE: "View submission",
    NotificationType.CLAIM_AVAILABLE: "View submission",
    NotificationType.MILESTONE_PAID: "View payment",
    NotificationType.ARBITER_VOTE: "View dispute",
}


def _format_amount(value: Any, asset_code: Any = None) -> str:
    raw = str(value)
    if "." in raw:
        raw = raw.rstrip("0").rstrip(".")
    return f"{raw} {asset_code or 'XLM'}"


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
        details.append(("Amount", _format_amount(payload["amount"], payload.get("asset_code"))))
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


#: Sending is serialised. Neither the httplib2 connection inside a Gmail service object nor a shared
#: ``Credentials`` is thread-safe, and two threads refreshing the same token at once is a race on it.
#: Transactional mail is a handful of messages, so serialising costs nothing measurable.
_gmail_lock = threading.Lock()

#: Attempts per message, and the waits between them. Deliberately short: a send is awaited inside the worker
#: job that triggered it, and only transient failures are retried at all, so a dead credential still fails on
#: the first attempt.
_GMAIL_ATTEMPTS: Final = 3
_GMAIL_WAITS: Final = (1.0, 2.0)


def _gmail_service(credentials_b64: str) -> Any:
    """Unpickle the configured credential and build an authorised Gmail client.

    The blob is the operator's own configuration and carries the same authority as this repository's code, so
    it is unpickled without validation. That is safe only because of where it comes from: it must never be
    sourced from the database, an upload, an API request or a shared config service. If that ever changes,
    this function has to change first.
    """
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    credentials = pickle.loads(base64.b64decode(credentials_b64))  # noqa: S301 - operator-supplied, see above
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    return build("gmail", "v1", credentials=credentials)


def _gmail_transient(exc: BaseException) -> bool:
    """Whether retrying this failure could plausibly succeed.

    A revoked token or a missing scope cannot be fixed by asking again, and retrying only delays a failure
    that is already certain. 429 and 5xx are Google saying "not now"; every other 4xx is "not ever".
    """
    from google.auth.exceptions import RefreshError, TransportError
    from googleapiclient.errors import HttpError

    if isinstance(exc, RefreshError):
        return False
    if isinstance(exc, HttpError):
        status = exc.status_code
        return status is not None and (status == 429 or status >= 500)
    return isinstance(exc, (TransportError, OSError, TimeoutError))


def _gmail_reason(exc: BaseException) -> str:
    """A one-line cause, carrying Google's own wording where there is one."""
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError

    if isinstance(exc, RefreshError):
        if "invalid_grant" in str(exc):
            # The one Gmail failure whose own message says nothing useful. Google has rejected the refresh
            # token itself, so it is dead rather than misconfigured and has to be replaced. The first cause
            # is by far the most common and is invisible from the error.
            return (
                "Google rejected the refresh token (invalid_grant). Mint a new one with "
                "scripts/mint_gmail_token.py. Causes, in order of likelihood: the OAuth consent screen is "
                "still in Testing (Google expires those tokens after 7 days — publish the app), access was "
                "revoked, the account password changed, or the OAuth client was deleted."
            )
        return f"RefreshError: {exc}"
    if isinstance(exc, HttpError):
        return f"HTTP {exc.status_code}: {exc}"
    return f"{type(exc).__name__}: {exc}"


class GmailEmailBackend:
    """Delivery through the Gmail API.

    ``google-api-python-client`` owns the send and ``google-auth`` owns the token lifecycle, so neither is
    reimplemented here. Both are synchronous (httplib2 underneath), so the send leaves the event loop or it
    stalls every other task for the length of a round trip.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _send_sync(self, mime: EmailMessage) -> None:
        # `raw` is a complete RFC 5322 message, serialised with the SMTP policy: CRLF endings and folded
        # headers, the same bytes any mail transport would put on the wire.
        raw = base64.urlsafe_b64encode(mime.as_bytes(policy=SMTP_POLICY)).decode("ascii")
        with _gmail_lock:
            service = _gmail_service(self.settings.gmail_credentials_b64)
            service.users().messages().send(userId="me", body={"raw": raw}).execute()

    async def send(self, message: OutgoingEmail) -> None:
        if not self.settings.gmail_credentials_b64:
            raise EmailSendError("GMAIL_CREDENTIALS_B64 is not set, so the Gmail transport cannot send.")
        mime = build_mime(message, self.settings.email_sender)
        for attempt in range(1, _GMAIL_ATTEMPTS + 1):
            try:
                # anyio rather than asyncio.to_thread: that is the pool FastAPI already sizes.
                await anyio.to_thread.run_sync(self._send_sync, mime)
                logger.info("email_sent", backend="gmail", to=message.to, subject=message.subject)
                return
            except Exception as exc:
                transient = _gmail_transient(exc)
                if not transient or attempt == _GMAIL_ATTEMPTS:
                    raise EmailSendError(
                        f"Gmail delivery failed ({'transient' if transient else 'permanent'}): "
                        f"{_gmail_reason(exc)}"
                    ) from exc
                logger.warning(
                    "email_send_retry",
                    backend="gmail",
                    to=message.to,
                    attempt=attempt,
                    error=_gmail_reason(exc),
                )
                await asyncio.sleep(_GMAIL_WAITS[attempt - 1])


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
        # An explicit "console" always wins. Otherwise a configured Gmail credential is the deployment's
        # intent, so it takes precedence over the SMTP default without needing EMAIL_BACKEND set as well.
        if settings.email_backend == "console":
            _backend = ConsoleEmailBackend()
        elif settings.gmail_credentials_b64 or settings.email_backend == "gmail":
            _backend = GmailEmailBackend(settings)
        else:
            _backend = SmtpEmailBackend(settings)
    return _backend


def set_email_backend(backend: EmailBackend | None) -> None:
    """Used by tests to capture outgoing mail."""
    global _backend
    _backend = backend
