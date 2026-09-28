"""Kafka producer/consumer factories (aiokafka) and a connectivity check."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient

from app.core.config import get_settings


def _serialize(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")


def create_producer() -> AIOKafkaProducer:
    settings = get_settings()
    return AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        client_id=f"{settings.app_name.lower()}-producer",
        acks="all",
        enable_idempotence=True,
        linger_ms=5,
        request_timeout_ms=15000,
        value_serializer=_serialize,
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )


def create_consumer(group_id: str, topics: list[str]) -> AIOKafkaConsumer:
    settings = get_settings()
    return AIOKafkaConsumer(
        *[settings.topic(t) for t in topics],
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=group_id,
        client_id=f"{group_id}-client",
        enable_auto_commit=False,  # commit only after the handler succeeded (at-least-once)
        auto_offset_reset="earliest",
        max_poll_records=50,
        session_timeout_ms=30000,
        heartbeat_interval_ms=3000,
    )


async def check_kafka(timeout: float = 3.0) -> bool:
    settings = get_settings()
    if not settings.kafka_enabled:
        return False
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers, request_timeout_ms=3000)
    try:
        async with asyncio.timeout(timeout):
            await admin.start()
            await admin.list_topics()
        return True
    except Exception:
        return False
    finally:
        try:
            await admin.close()
        except Exception:  # noqa: S110 - best-effort cleanup
            pass
