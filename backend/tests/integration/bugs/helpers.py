"""Scenario builders shared by the regression tests (API-level, `FakeStellarChain` escrow, real signatures)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import Role, User
from tests.integration.api.conftest import (
    ARBITER,
    ApiClient,
    bounty_payload,
    chain_action,
    link_wallet,
    register,
    sign_xdr,
    verify_email,
)


def handle(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:6]}"


async def requester(client_factory: Any, mail: Any, prefix: str = "req") -> tuple[ApiClient, str]:
    client = client_factory()
    await register(client, handle(prefix))
    await verify_email(client, mail)
    wallet = await link_wallet(client)
    return client, wallet


async def contributor(client_factory: Any, prefix: str = "dev") -> tuple[ApiClient, str]:
    client = client_factory()
    await register(client, handle(prefix))
    wallet = await link_wallet(client)
    return client, wallet


async def published(client: ApiClient, **overrides: Any) -> dict[str, Any]:
    bounty = await client.post("/bounties", bounty_payload(**overrides), expected=201)
    return await client.post(f"/bounties/{bounty['id']}/publish")


async def fund(client: ApiClient, bid: str, wallet: str, amount: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"wallet_address": wallet}
    if amount is not None:
        body["amount"] = amount
    return await chain_action(client, f"/bounties/{bid}/funding/prepare", body)


async def funded(client: ApiClient, wallet: str, **overrides: Any) -> dict[str, Any]:
    bounty = await published(client, **overrides)
    await fund(client, bounty["id"], wallet)
    return await client.get(f"/bounties/{bounty['id']}")


async def apply(contrib: ApiClient, bid: str) -> dict[str, Any]:
    return await contrib.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "I have shipped this exact kind of work before and can start today."},
        expected=201,
    )


async def assign(req: ApiClient, contrib: ApiClient, bid: str) -> str:
    application = await apply(contrib, bid)
    accepted = await req.post(f"/applications/{application['id']}/accept", {})
    return str(accepted["assignment_id"])


async def assign_onchain(req: ApiClient, bid: str, wallet: str, assignment_id: str) -> dict[str, Any]:
    return await chain_action(
        req,
        f"/bounties/{bid}/chain/prepare",
        {"action": "ASSIGN", "wallet_address": wallet, "assignment_id": assignment_id},
    )


async def submit_work(contrib: ApiClient, bid: str) -> dict[str, Any]:
    return await contrib.post(
        f"/bounties/{bid}/submissions",
        {"description": "Delivered the full scope with tests, docs and a short walkthrough video."},
        expected=201,
    )


async def payout(req: ApiClient, bid: str, wallet: str, submission_id: str) -> dict[str, Any]:
    return await chain_action(
        req, f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": submission_id}
    )


async def action(req: ApiClient, bid: str, name: str, wallet: str, **extra: Any) -> dict[str, Any]:
    return await chain_action(
        req, f"/bounties/{bid}/chain/prepare", {"action": name, "wallet_address": wallet, **extra}
    )


async def set_role(db_session: AsyncSession, username: str, role: Role) -> None:
    await db_session.execute(update(User).where(User.username == username).values(role=role))
    await db_session.commit()


async def moderator(client_factory: Any, db_session: AsyncSession) -> ApiClient:
    client = client_factory()
    me = await register(client, handle("mod"))
    await set_role(db_session, me["username"], Role.MODERATOR)
    return client


def signed(prepared: dict[str, Any], wallet: str) -> dict[str, str]:
    """Submit body for a prepared transaction, signed by ``wallet``'s keypair (what the browser wallet does)."""
    return {"signed_xdr": sign_xdr(prepared["unsigned_xdr"], wallet)}


async def submit_signed(client: ApiClient, prepared: dict[str, Any], wallet: str, **kw: Any) -> Any:
    """Signs a prepared transaction with ``wallet`` and submits it (no status assertion beyond ``kw``)."""
    return await client.post(
        f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet), **kw
    )


async def arbiter(moderator_client: ApiClient) -> str:
    """Links the test arbiter keypair to a moderator and returns its address (the configured escrow arbiter)."""
    address = str((await moderator_client.get("/config/public"))["arbiter_address"])
    assert address == ARBITER.public_key
    await link_wallet(moderator_client, ARBITER)
    return address


async def status_of(client: ApiClient, bid: str) -> str:
    return str((await client.get(f"/bounties/{bid}"))["status"])
