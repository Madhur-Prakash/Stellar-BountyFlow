"""Scenario builders for the compliance and operations tests."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import Role, User
from tests.integration.api.conftest import (
    ApiClient,
    bounty_payload,
    chain_action,
    link_wallet,
    register,
    verify_email,
)

PASSWORD = "Str0ng-passphrase!"  # what tests.integration.api.conftest.register uses


def handle(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


async def requester(client_factory: Any, mail: Any, prefix: str = "req") -> tuple[ApiClient, str]:
    client = client_factory()
    await register(client, handle(prefix))
    await verify_email(client, mail)
    return client, await link_wallet(client)


async def staff(client_factory: Any, db_session: AsyncSession, role: Role = Role.ADMIN) -> ApiClient:
    client = client_factory()
    me = await register(client, handle(role.value.lower()))
    await db_session.execute(update(User).where(User.id == uuid.UUID(me["id"])).values(role=role))
    await db_session.commit()
    return client


async def published(client: ApiClient, **overrides: Any) -> dict[str, Any]:
    bounty = await client.post("/bounties", bounty_payload(**overrides), expected=201)
    return await client.post(f"/bounties/{bounty['id']}/publish")


async def funded(client: ApiClient, wallet: str, **overrides: Any) -> dict[str, Any]:
    bounty = await published(client, **overrides)
    await chain_action(client, f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    return await client.get(f"/bounties/{bounty['id']}")


async def approved_submission(
    client_factory: Any, owner: ApiClient, bounty_id: str, contributor: ApiClient | None = None
) -> tuple[ApiClient, str, dict[str, Any]]:
    """A contributor (with a verified wallet) whose submission to ``bounty_id`` was approved, not yet paid."""
    if contributor is None:
        contributor = client_factory()
        await register(contributor, handle("dev"))
    wallet = await link_wallet(contributor)
    application = await contributor.post(
        f"/bounties/{bounty_id}/applications",
        {"cover_message": "I have shipped this exact kind of work many times before."},
        expected=201,
    )
    await owner.post(f"/applications/{application['id']}/accept", {"note": "Welcome aboard"})
    submission = await contributor.post(
        f"/bounties/{bounty_id}/submissions",
        {
            "description": "Delivered the work with tests and documentation.",
            "evidence_url": "https://example.com/pr/1",
        },
        expected=201,
    )
    await owner.post(f"/submissions/{submission['id']}/approve", {"feedback": "Great work"})
    return contributor, wallet, submission
