"""Shared, pooled Soroban RPC client."""

from __future__ import annotations

import asyncio

from stellar_sdk import SorobanServerAsync
from stellar_sdk.client.aiohttp_client import AiohttpClient

from app.blockchain.config import get_network

_server: SorobanServerAsync | None = None


def get_soroban() -> SorobanServerAsync:
    global _server
    if _server is None:
        net = get_network()
        http = AiohttpClient(
            pool_size=20,
            request_timeout=net.rpc_timeout_seconds,
            post_timeout=net.rpc_timeout_seconds,
            user_agent="bountyflow-api",
        )
        _server = SorobanServerAsync(net.soroban_rpc_url, client=http)
    return _server


async def close_soroban() -> None:
    global _server
    if _server is not None:
        await _server.close()
    _server = None


async def check_rpc(timeout: float = 4.0) -> bool:
    try:
        async with asyncio.timeout(timeout):
            health = await get_soroban().get_health()
        return health.status == "healthy"
    except Exception:
        return False
