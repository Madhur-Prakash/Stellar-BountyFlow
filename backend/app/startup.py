"""Optional startup automation: apply migrations and run the idempotent seed.

Controlled by RUN_MIGRATIONS_ON_STARTUP and SEED_ON_STARTUP. Both steps run while holding a Postgres advisory lock,
so several API replicas booting at once never run migrations or seeding concurrently.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_engine

logger = get_logger(__name__)

# Arbitrary, stable 64-bit key identifying the BountyFlow bootstrap lock.
BOOTSTRAP_LOCK_KEY = 7_265_110_392_184_401
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _upgrade_head() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    command.upgrade(cfg, "head")


async def run_startup_tasks() -> None:
    settings = get_settings()
    if not (settings.run_migrations_on_startup or settings.seed_on_startup):
        return
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": BOOTSTRAP_LOCK_KEY})
        try:
            if settings.run_migrations_on_startup:
                logger.info("startup_migrations_begin")
                # Alembic's env.py drives its own event loop, so run it in a worker thread.
                await asyncio.to_thread(_upgrade_head)
                logger.info("startup_migrations_complete")
            if settings.seed_on_startup and settings.is_production:
                logger.warning("startup_seed_skipped", reason="seeding is disabled in staging/production")
            elif settings.seed_on_startup:
                from app.scripts.seed import seed

                logger.info("startup_seed_begin")
                summary = await seed()
                logger.info("startup_seed_complete", **summary)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": BOOTSTRAP_LOCK_KEY})
            await conn.commit()
