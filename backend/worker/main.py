"""BountyFlow worker process: Kafka consumers, the outbox relay, periodic jobs, and a Redis heartbeat.

Run with ``bountyflow-worker`` or ``python -m worker.main``. SIGINT/SIGTERM trigger a graceful shutdown:
components stop taking new work, in-flight events finish (or stay uncommitted for redelivery), and every
client is closed.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sys
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaProducer

from app.cache import keys
from app.cache.redis import close_redis, get_redis
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger, shutdown_logging
from app.core.security import utcnow
from app.db.session import dispose_engine
from app.messaging.kafka import create_producer
from app.messaging.outbox import Publisher
from app.messaging.registry import Consumer, all_consumers
from worker.consumer import ConsumerRunner
from worker.jobs import lifecycle, reconciliation
from worker.jobs.outbox_relay import InProcessDispatcher, kafka_publisher, run_outbox_relay
from worker.retry import backoff_delay, interruptible_sleep

logger = get_logger(__name__)

WORKER_NAME = "main"
HEARTBEAT_INTERVAL = 10.0
HEARTBEAT_TTL = 30
SHUTDOWN_GRACE_SECONDS = 20.0


async def supervise(name: str, factory: Callable[[], Awaitable[None]], stop: asyncio.Event) -> None:
    """Keep a long-running component alive: restart it with backoff if it crashes before shutdown."""
    failures = 0
    while not stop.is_set():
        try:
            await factory()
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            failures += 1
            logger.exception("worker_component_crashed", component=name, failures=failures)
        if stop.is_set():
            break
        delay = backoff_delay(max(failures, 1))
        logger.warning("worker_component_restarting", component=name, delay_seconds=round(delay, 2))
        await interruptible_sleep(delay, stop)


async def heartbeat(stop: asyncio.Event, settings: Settings) -> None:
    key = keys.worker_heartbeat(WORKER_NAME)
    host, pid = socket.gethostname(), os.getpid()
    while not stop.is_set():
        value = json.dumps(
            {"at": utcnow().isoformat(), "host": host, "pid": pid, "kafka_enabled": settings.kafka_enabled}
        )
        try:
            await get_redis().set(key, value, ex=HEARTBEAT_TTL)
        except Exception as exc:
            logger.warning("worker_heartbeat_failed", error=str(exc))
        await interruptible_sleep(HEARTBEAT_INTERVAL, stop)
    try:
        await get_redis().delete(key)
    except Exception as exc:
        logger.debug("worker_heartbeat_clear_failed", error=str(exc))


async def start_producer(stop: asyncio.Event) -> AIOKafkaProducer | None:
    """Start the Kafka producer, retrying until Kafka is reachable. Returns None if shutdown came first."""
    attempt = 0
    while not stop.is_set():
        attempt += 1
        producer = create_producer()
        try:
            await producer.start()
        except Exception as exc:
            try:
                await producer.stop()
            except Exception as stop_exc:
                logger.debug("kafka_producer_cleanup_failed", error=str(stop_exc))
            delay = backoff_delay(attempt)
            logger.warning(
                "kafka_producer_unavailable", error=str(exc), attempt=attempt, retry_in=round(delay, 2)
            )
            await interruptible_sleep(delay, stop)
            continue
        logger.info("kafka_producer_started")
        return producer
    return None


def install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_stop(signame: str) -> None:
        if not stop.is_set():
            logger.info("worker_shutdown_requested", signal=signame)
            stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop, sig.name)
        except (NotImplementedError, RuntimeError):
            # Windows event loops do not support add_signal_handler: use a plain handler that hands the
            # request back to the loop thread.
            signal.signal(
                sig,
                lambda signum, _frame: loop.call_soon_threadsafe(request_stop, signal.Signals(signum).name),
            )
    if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
        signal.signal(
            signal.SIGBREAK, lambda signum, _frame: loop.call_soon_threadsafe(request_stop, "SIGBREAK")
        )


async def _close_clients(producer: AIOKafkaProducer | None) -> None:
    from app.blockchain.client import close_soroban

    if producer is not None:
        try:
            await producer.stop()
        except Exception as exc:
            logger.warning("kafka_producer_stop_failed", error=str(exc))
    for name, closer in (("redis", close_redis), ("database", dispose_engine), ("soroban", close_soroban)):
        try:
            await closer()
        except Exception as exc:
            logger.warning("client_close_failed", client=name, error=str(exc))


async def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json, service="worker")
    stop = asyncio.Event()
    install_signal_handlers(stop)
    consumers: list[Consumer] = all_consumers()
    producer: AIOKafkaProducer | None = None
    tasks: list[asyncio.Task[None]] = []
    try:
        publisher: Publisher
        if settings.kafka_enabled:
            producer = await start_producer(stop)
            if producer is None:
                return
            publisher = kafka_publisher(producer, settings)
            for consumer in consumers:
                runner = ConsumerRunner(consumer, producer, stop, settings=settings)
                tasks.append(asyncio.create_task(supervise(f"consumer:{consumer.name}", runner.run, stop)))
        else:
            logger.warning("kafka_disabled_in_process_dispatch", consumers=[c.name for c in consumers])
            publisher = InProcessDispatcher(consumers, stop)

        tasks += [
            asyncio.create_task(supervise("outbox-relay", lambda: run_outbox_relay(publisher, stop), stop)),
            asyncio.create_task(supervise(lifecycle.JOB_NAME, lambda: lifecycle.run(stop), stop)),
            asyncio.create_task(supervise(reconciliation.JOB_NAME, lambda: reconciliation.run(stop), stop)),
            asyncio.create_task(supervise("heartbeat", lambda: heartbeat(stop, settings), stop)),
        ]
        logger.info(
            "worker_started",
            kafka_enabled=settings.kafka_enabled,
            consumers=[f"{c.name}:{','.join(c.topics)}" for c in consumers],
            blockchain_mode=settings.blockchain_mode,
        )
        await stop.wait()
        logger.info("worker_stopping", grace_seconds=SHUTDOWN_GRACE_SECONDS)
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_GRACE_SECONDS)
            for task in pending:
                task.cancel()
            if pending:
                logger.warning("worker_tasks_cancelled", count=len(pending))
                await asyncio.gather(*pending, return_exceptions=True)
    finally:
        stop.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _close_clients(producer)
        logger.info("worker_stopped")


def run() -> None:
    # psycopg's async driver requires a selector event loop; Windows defaults to the proactor loop.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        asyncio.run(main(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_logging()


if __name__ == "__main__":
    run()
