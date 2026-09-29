"""GitHub webhook receiver: re-checks linked pull requests when they change.

Off unless ``GITHUB_WEBHOOK_SECRET`` is set. Every delivery must carry ``X-Hub-Signature-256`` (HMAC-SHA256 of the
raw body with the secret), compared in constant time; unsigned or wrongly signed deliveries are refused. The
payload is only used to find which pull requests to re-check: their state always comes from the REST API, never
from the webhook body. Deliveries are de-duplicated on ``X-GitHub-Delivery``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.exceptions import NotAuthenticated, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.modules.github import service as pr_service

logger = get_logger(__name__)

HANDLED_EVENTS = frozenset({"pull_request", "pull_request_review", "check_run", "check_suite", "status"})
DELIVERY_TTL_SECONDS = 24 * 3600


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(signature(secret, body), header)


def targets(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Which pull requests a delivery concerns: ``{"owner", "repo", "number"}`` and/or ``{"head_sha"}``."""
    repo = payload.get("repository") or {}
    full_name = str(repo.get("full_name") or "")
    owner, _, name = full_name.partition("/")
    found: dict[str, Any] = {}
    if event in ("pull_request", "pull_request_review"):
        pr = payload.get("pull_request") or {}
        number = pr.get("number") or payload.get("number")
        if owner and name and isinstance(number, int):
            found.update(owner=owner, repo=name, number=number)
        sha = (pr.get("head") or {}).get("sha")
        if isinstance(sha, str):
            found["head_sha"] = sha
    elif event == "check_run":
        sha = (payload.get("check_run") or {}).get("head_sha")
        if isinstance(sha, str):
            found["head_sha"] = sha
    elif event == "check_suite":
        sha = (payload.get("check_suite") or {}).get("head_sha")
        if isinstance(sha, str):
            found["head_sha"] = sha
    elif event == "status":
        sha = payload.get("sha")
        if isinstance(sha, str):
            found["head_sha"] = sha
    return found


async def _first_delivery(delivery_id: str | None) -> bool:
    if not delivery_id:
        return True
    try:
        return bool(
            await get_redis().set(
                f"{keys.PREFIX}:github:delivery:{delivery_id[:64]}", "1", nx=True, ex=DELIVERY_TTL_SECONDS
            )
        )
    except Exception:
        return True  # at worst the same pull request is re-checked twice


async def handle_delivery(
    session: AsyncSession,
    *,
    body: bytes,
    event: str | None,
    signature_header: str | None,
    delivery_id: str | None,
) -> dict[str, Any]:
    secret = get_settings().github_webhook_secret
    if not secret:
        raise NotFound("GitHub webhooks are not enabled on this server.")
    if not verify_signature(secret, body, signature_header):
        logger.warning("github_webhook_bad_signature", delivery=delivery_id)
        raise NotAuthenticated("Invalid webhook signature.", code="invalid_signature")
    if event == "ping":
        return {"ok": True, "rechecks": 0}
    if event not in HANDLED_EVENTS:
        return {"ok": True, "rechecks": 0, "ignored": event}
    if not await _first_delivery(delivery_id):
        return {"ok": True, "rechecks": 0, "duplicate": True}
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise ValidationFailed("The webhook body is not JSON.") from exc
    if not isinstance(payload, dict):
        raise ValidationFailed("The webhook body is not a JSON object.")
    found = targets(event, payload)
    rechecks = await pr_service.mark_due(session, **found) if found else 0
    logger.info("github_webhook_received", github_event=event, rechecks=rechecks)
    return {"ok": True, "rechecks": rechecks}
