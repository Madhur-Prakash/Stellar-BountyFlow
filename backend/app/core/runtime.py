"""Process entry-point helpers."""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


def loop_factory() -> asyncio.AbstractEventLoop:
    """psycopg's async driver cannot run on Windows' default ProactorEventLoop; use a selector loop there."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop(selectors.SelectSelector())
    return asyncio.new_event_loop()


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro, loop_factory=loop_factory)
