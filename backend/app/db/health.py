"""Database connectivity check."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import get_engine


async def check_database(timeout: float = 3.0) -> bool:
    try:
        async with asyncio.timeout(timeout):
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
