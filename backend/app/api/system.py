"""Health, readiness, and public configuration endpoints.

Health responses report only coarse component status — never hostnames, versions of dependencies, or secrets.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Response, status

from app.blockchain.client import check_rpc
from app.blockchain.config import get_network
from app.cache.redis import check_redis
from app.core.config import get_settings
from app.core.schemas import APIModel
from app.db.health import check_database
from app.messaging.kafka import check_kafka

health_router = APIRouter(tags=["health"])
config_router = APIRouter(tags=["config"])

Check = Literal["ok", "error", "disabled"]


class Health(APIModel):
    status: Literal["ok"]
    service: str
    version: str


class Readiness(APIModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, Check]


@health_router.get("/health", response_model=Health)
async def health() -> Health:
    s = get_settings()
    return Health(status="ok", service="bountyflow-api", version=s.app_version)


@health_router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/health/ready", response_model=Readiness)
async def ready(response: Response) -> Readiness:
    settings = get_settings()
    db, redis, kafka, rpc = await asyncio.gather(
        check_database(),
        check_redis(),
        check_kafka() if settings.kafka_enabled else asyncio.sleep(0, result=None),
        check_rpc(),
    )
    checks: dict[str, Check] = {
        "database": "ok" if db else "error",
        "redis": "ok" if redis else "error",
        "kafka": "disabled" if kafka is None else ("ok" if kafka else "error"),
        "blockchain_rpc": "ok" if rpc else "error",
    }
    # The API can serve traffic without Kafka (the outbox buffers events) or the RPC (chain actions fail cleanly),
    # but not without its database.
    if not db:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    overall: Literal["ok", "degraded"] = "ok" if all(v != "error" for v in checks.values()) else "degraded"
    return Readiness(status=overall, checks=checks)


class PublicConfig(APIModel):
    app_name: str
    network: str
    network_passphrase: str
    horizon_url: str
    soroban_rpc_url: str
    explorer_base_url: str
    contract_id: str | None
    contract_explorer_url: str | None
    native_asset_contract_id: str | None
    arbiter_address: str | None
    blockchain_mode: Literal["testnet", "mainnet"]


@config_router.get("/config/public", response_model=PublicConfig)
async def public_config() -> PublicConfig:
    s = get_settings()
    n = get_network()
    return PublicConfig(
        app_name=s.app_name,
        network=n.network,
        network_passphrase=n.passphrase,
        horizon_url=n.horizon_url,
        soroban_rpc_url=n.soroban_rpc_url,
        explorer_base_url=n.explorer_base_url,
        contract_id=n.contract_id,
        contract_explorer_url=n.contract_url(),
        native_asset_contract_id=n.native_asset_contract_id,
        arbiter_address=n.arbiter_address,
        blockchain_mode=s.blockchain_mode,
    )
