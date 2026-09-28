"""Email templates: correct links, escaping, plain-text alternatives, and no token leakage into logs."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import get_settings
from app.modules.notifications import email as mail
from app.modules.notifications.models import NotificationType

RAW_TOKEN = "tok_Sup3rS3cret-Value_1234567890abcdef"


class RecordingLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def _record(self, event: str, **fields: Any) -> None:
        self.records.append((event, fields))

    info = warning = error = debug = exception = _record

    def dump(self) -> str:
        return repr(self.records)


def test_verify_email_link_and_expiry() -> None:
    rendered = mail.render_verify_email("Ada <script>", RAW_TOKEN)
    link = f"{get_settings().frontend_url.rstrip('/')}/verify-email?token={RAW_TOKEN}"
    assert link in rendered.text
    assert f'href="{link}"' in rendered.html
    assert "expires in 1 day" in rendered.text
    # Autoescaping: user-controlled names never inject markup.
    assert "<script>" not in rendered.html
    assert "Ada &lt;script&gt;" in rendered.html
    assert rendered.subject == "Confirm your email for BountyFlow"


def test_password_reset_link() -> None:
    rendered = mail.render_password_reset("Ada", RAW_TOKEN)
    url = urlparse(next(line for line in rendered.text.splitlines() if "reset-password" in line).strip())
    assert url.path == "/reset-password"
    assert parse_qs(url.query) == {"token": [RAW_TOKEN]}
    assert "expires in 1 hour" in rendered.text
    assert "signs you out on every device" in rendered.html


def test_notification_email_brand_links_and_network_label() -> None:
    settings = get_settings()
    rendered = mail.render_notification(
        recipient_name="Grace",
        notification_type=NotificationType.PAYMENT_CONFIRMED,
        title="Payment received",
        message="You received 10 XLM for “Fix bug”.",
        link="/app/payments",
        payload={"amount": "10.0000000"},
    )
    base = settings.frontend_url.rstrip("/")
    assert f'href="{base}/app/payments"' in rendered.html
    assert f"{base}/app/settings" in rendered.html  # preference management link
    assert "#0B1631" in rendered.html
    assert "#4C7DFF" in rendered.html
    assert "10 XLM" in rendered.html
    network = f"Stellar {settings.network_label.title()}"  # the real network the payment was verified on
    assert network in rendered.html
    assert f"Network: {network}" in rendered.text
    assert rendered.subject == f"Payment received | {settings.app_name}"


def test_notification_email_without_link_has_no_button() -> None:
    rendered = mail.render_notification(
        recipient_name="Grace",
        notification_type=NotificationType.SYSTEM,
        title="Heads up",
        message="Something happened.",
        link=None,
    )
    assert "If the button does not work" not in rendered.html
    assert "Something happened." in rendered.text


def test_build_mime_has_text_and_html_parts() -> None:
    rendered = mail.render_verify_email("Ada", RAW_TOKEN)
    mime = mail.build_mime(
        mail.OutgoingEmail(
            to="ada@example.com", subject=rendered.subject, html=rendered.html, text=rendered.text
        ),
        "BountyFlow <no-reply@bountyflow.local>",
    )
    types = [part.get_content_type() for part in mime.iter_parts()]
    assert types == ["text/plain", "text/html"]
    assert mime["To"] == "ada@example.com"


async def test_console_backend_never_logs_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = RecordingLogger()
    monkeypatch.setattr(mail, "logger", recorder)
    rendered = mail.render_password_reset("Ada", RAW_TOKEN)
    await mail.ConsoleEmailBackend().send(
        mail.OutgoingEmail(
            to="ada@example.com", subject=rendered.subject, html=rendered.html, text=rendered.text
        )
    )
    assert recorder.records, "expected the send to be logged"
    assert RAW_TOKEN not in recorder.dump()
    assert "ada@example.com" in recorder.dump()


async def test_smtp_failure_is_wrapped_without_leaking_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiosmtplib

    recorder = RecordingLogger()
    monkeypatch.setattr(mail, "logger", recorder)

    async def failing_send(*args: Any, **kwargs: Any) -> None:
        raise aiosmtplib.SMTPConnectError("connection refused")

    monkeypatch.setattr(aiosmtplib, "send", failing_send)
    rendered = mail.render_verify_email("Ada", RAW_TOKEN)
    with pytest.raises(mail.EmailSendError) as excinfo:
        await mail.SmtpEmailBackend().send(
            mail.OutgoingEmail(
                to="ada@example.com", subject=rendered.subject, html=rendered.html, text=rendered.text
            )
        )
    assert RAW_TOKEN not in str(excinfo.value)
    assert RAW_TOKEN not in recorder.dump()
