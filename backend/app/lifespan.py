"""Application lifespan: logging, optional migrations/seed, and graceful shutdown of pooled clients."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.blockchain.client import close_soroban
from app.blockchain.config import get_network
from app.cache.redis import close_redis
from app.core.config import get_settings
from app.core.logging import get_logger, shutdown_logging
from app.db.session import dispose_engine
from app.startup import run_startup_tasks

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    network = get_network()
    await run_startup_tasks()
    logger.info(
        "api_started",
        env=settings.app_env,
        network=network.network,
        blockchain_mode=network.mode,
        contract_configured=network.is_configured,
        kafka_enabled=settings.kafka_enabled,
    )
    try:
        yield
    finally:
        logger.info("api_stopping")
        await close_soroban()
        await close_redis()
        await dispose_engine()
        shutdown_logging()
