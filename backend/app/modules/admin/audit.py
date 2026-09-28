"""Append-only audit trail helper. Call inside the same transaction as the state change."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_context
from app.modules.admin.models import AuditLog


def record(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    bounty_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    is_public: bool = True,
) -> AuditLog:
    ctx = get_context()
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        bounty_id=bounty_id,
        metadata_=metadata or {},
        is_public=is_public,
        request_id=ctx.get("request_id"),
    )
    session.add(entry)
    return entry
