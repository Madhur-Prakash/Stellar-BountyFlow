"""Retry policy for event handlers: bounded exponential backoff with jitter, and the retry vs. dead-letter
decision. Pure functions plus one small driver, shared by the Kafka consumers and the in-process dispatcher."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.core.exceptions import AppError
from app.messaging.processing import MalformedEvent

BASE_DELAY = 0.5
MAX_DELAY = 30.0


class Decision(StrEnum):
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    DEAD_LETTERED = "dead_lettered"
    ABORTED = "aborted"  # shutdown requested while waiting to retry; the message must not be committed


def is_permanent(exc: BaseException) -> bool:
    """Errors that will fail identically on every attempt: malformed messages and domain rejections (4xx-style
    ``AppError``). Infrastructure failures (DB, RPC, SMTP, 5xx ``AppError``) are transient."""
    if isinstance(exc, MalformedEvent):
        return True
    return isinstance(exc, AppError) and exc.status_code < 500


def decide(exc: BaseException, attempt: int, max_retries: int) -> Decision:
    """``attempt`` is the number of attempts made so far (1-based). ``max_retries`` retries follow the first
    attempt, so an event is tried at most ``max_retries + 1`` times before being dead-lettered."""
    if is_permanent(exc) or attempt > max_retries:
        return Decision.DEAD_LETTER
    return Decision.RETRY


def backoff_delay(
    attempt: int,
    *,
    base: float = BASE_DELAY,
    cap: float = MAX_DELAY,
    rng: Callable[[], float] = random.random,
) -> float:
    """Exponential backoff with "equal jitter": half the exponential delay is fixed, half is random, so retries
    spread out while still growing. ``attempt`` 1 -> ~[0.25, 0.5]s, 2 -> ~[0.5, 1]s, ... capped at ``cap``."""
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    return exp / 2 + rng() * (exp / 2)


def dlq_headers(
    *,
    consumer: str,
    topic: str,
    partition: int | None,
    offset: int | None,
    error: BaseException,
    attempts: int,
) -> list[tuple[str, bytes]]:
    message = str(error) or type(error).__name__
    values = {
        "x-consumer": consumer,
        "x-original-topic": topic,
        "x-original-partition": "" if partition is None else str(partition),
        "x-original-offset": "" if offset is None else str(offset),
        "x-error-type": type(error).__name__,
        "x-error-message": message[:1000],
        "x-attempts": str(attempts),
        "x-permanent": "true" if is_permanent(error) else "false",
    }
    return [(k, v.encode("utf-8")) for k, v in values.items()]


async def interruptible_sleep(delay: float, stop: asyncio.Event | None) -> bool:
    """Sleep for ``delay`` seconds. Returns True if ``stop`` was set in the meantime."""
    if stop is None:
        await asyncio.sleep(delay)
        return False
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except TimeoutError:
        return False
    return True


@dataclass
class RetryResult:
    outcome: Outcome
    attempts: int
    error: BaseException | None = None


RetryCallback = Callable[[BaseException, int, float], None]


async def run_with_retries(
    fn: Callable[[], Awaitable[Any]],
    *,
    max_retries: int,
    stop: asyncio.Event | None = None,
    base: float = BASE_DELAY,
    cap: float = MAX_DELAY,
    rng: Callable[[], float] = random.random,
    sleep: Callable[[float, asyncio.Event | None], Awaitable[bool]] = interruptible_sleep,
    on_retry: RetryCallback | None = None,
) -> RetryResult:
    attempt = 0
    while True:
        attempt += 1
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if decide(exc, attempt, max_retries) is Decision.DEAD_LETTER:
                return RetryResult(Outcome.DEAD_LETTERED, attempt, exc)
            delay = backoff_delay(attempt, base=base, cap=cap, rng=rng)
            if on_retry is not None:
                on_retry(exc, attempt, delay)
            if await sleep(delay, stop):
                return RetryResult(Outcome.ABORTED, attempt, exc)
            continue
        return RetryResult(Outcome.SUCCEEDED, attempt)
