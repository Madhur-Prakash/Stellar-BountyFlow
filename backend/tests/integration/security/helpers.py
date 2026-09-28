"""Shared flows for the security regression suite."""

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


async def new_requester(client_factory: Any, mail: Any, name: str = "req") -> tuple[ApiClient, str]:
    """A registered, email-verified user with a wallet verified through the real SEP-10 challenge."""
    client = client_factory()
    await register(client, f"{name}_{uuid.uuid4().hex[:6]}")
    await verify_email(client, mail)
    wallet = await link_wallet(client)
    return client, wallet


async def new_user(client_factory: Any, name: str = "user") -> ApiClient:
    client = client_factory()
    await register(client, f"{name}_{uuid.uuid4().hex[:6]}")
    return client


async def published(client: ApiClient, **overrides: Any) -> dict[str, Any]:
    bounty = await client.post("/bounties", bounty_payload(**overrides), expected=201)
    return await client.post(f"/bounties/{bounty['id']}/publish")


async def funded(client: ApiClient, wallet: str, **overrides: Any) -> dict[str, Any]:
    bounty = await published(client, **overrides)
    await chain_action(client, f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    return await client.get(f"/bounties/{bounty['id']}")


async def assigned_contributor(
    client_factory: Any, requester: ApiClient, bounty_id: str, name: str = "contrib"
) -> tuple[ApiClient, str, dict[str, Any]]:
    """A contributor who applied and was accepted (off-chain assignment only). Returns (client, wallet, app)."""
    contributor = await new_user(client_factory, name)
    wallet = await link_wallet(contributor)
    application = await contributor.post(
        f"/bounties/{bounty_id}/applications",
        {"cover_message": "I have shipped this exact kind of work many times before."},
        expected=201,
    )
    accepted = await requester.post(f"/applications/{application['id']}/accept", {"note": "private note"})
    return contributor, wallet, accepted


async def set_role(db_session: AsyncSession, client: ApiClient, role: Role) -> None:
    assert client.me is not None
    await db_session.execute(update(User).where(User.id == uuid.UUID(client.me["id"])).values(role=role))
    await db_session.commit()
