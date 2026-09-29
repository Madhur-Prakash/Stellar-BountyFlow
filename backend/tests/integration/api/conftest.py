"""API-level fixtures: a fresh app instance per test, bound to the isolated test database and fakeredis.

The app runs in Testnet configuration with `FakeStellarChain` (tests/support) injected as the chain adapter: it
builds real Stellar transaction XDR, tests sign it with real keypairs (the backend's real signature verification
runs), and the in-memory contract model executes it. The real-network equivalent is
tests/contract/test_testnet_flow.py (opt-in).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from stellar_sdk import Keypair, TransactionEnvelope

from app.blockchain import transactions as chain_module
from app.blockchain.config import get_network
from app.core.config import get_settings
from app.messaging.events import EventEnvelope
from app.messaging.outbox import relay_batch
from app.messaging.processing import process_event
from app.messaging.registry import all_consumers
from tests.support.fake_chain import FakeStellarChain

# Deterministic test-only arbiter identity (the real arbiter key never leaves the Stellar CLI key store).
ARBITER = Keypair.from_raw_ed25519_seed(hashlib.sha256(b"bountyflow-test-arbiter").digest())

# Every keypair a test links as a wallet, so helpers can sign on its behalf.
KEYRING: dict[str, Keypair] = {ARBITER.public_key: ARBITER}

# Deterministic test-only fee sponsor (the real sponsor secret lives only in the root .env).
SPONSOR = Keypair.from_raw_ed25519_seed(hashlib.sha256(b"bountyflow-test-sponsor").digest())
WEB_AUTH_CONTRACT = "CB3GXQ2BW2AHSIWUITLVBKODKPUHIK5DLEPWIIWTKLTKLA6TE24PLSZX"

API_ENV = {
    "APP_ENV": "test",
    "BLOCKCHAIN_MODE": "testnet",
    "STELLAR_NETWORK": "testnet",
    "STELLAR_NETWORK_PASSPHRASE": "Test SDF Network ; September 2015",
    "SOROBAN_CONTRACT_ID": "CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY",
    "STELLAR_NATIVE_ASSET_CONTRACT_ID": "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
    "STELLAR_ARBITER_ADDRESS": ARBITER.public_key,
    # Escrow v2: one arbiter (whatever the local .env configures) and the production review-window bounds.
    "STELLAR_ARBITER_ADDRESSES": "",
    "STELLAR_ARBITER_THRESHOLD": "1",
    "SOROBAN_CONTRACT_VERSION": "2",
    "ESCROW_MIN_REVIEW_WINDOW_SECONDS": "86400",
    "ESCROW_DEFAULT_REVIEW_WINDOW_SECONDS": "604800",
    "STELLAR_SPONSOR_SECRET": SPONSOR.secret,
    "WEB_AUTH_CONTRACT_ID": WEB_AUTH_CONTRACT,
    "KAFKA_ENABLED": "false",
    "EMAIL_BACKEND": "console",
    "RUN_MIGRATIONS_ON_STARTUP": "false",
    "SEED_ON_STARTUP": "false",
    "COOKIE_SECURE": "false",
    "FRONTEND_URL": "http://frontend.test",
    "LOG_LEVEL": "WARNING",
}


def _reset_caches() -> None:
    get_settings.cache_clear()
    get_network.cache_clear()
    chain_module.set_adapter(None)


@pytest.fixture
async def chain(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[FakeStellarChain]:
    for key, value in API_ENV.items():
        monkeypatch.setenv(key, value)
    _reset_caches()
    fake = FakeStellarChain(get_network())
    chain_module.set_adapter(fake)
    try:
        yield fake
    finally:
        _reset_caches()


@pytest.fixture
async def app(db: AsyncEngine, chain: FakeStellarChain) -> Any:
    from app.main import create_app

    return create_app()


class ApiClient:
    """Cookie-aware client that sends the CSRF double-submit header automatically."""

    def __init__(self, app: Any) -> None:
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")
        self.me: dict[str, Any] | None = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        expected: int | tuple[int, ...] | None = None,
        csrf: bool = True,
        **kwargs: Any,
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        token = self.http.cookies.get("bf_csrf")
        if csrf and token:
            headers["X-CSRF-Token"] = token
        response = await self.http.request(method, f"/api/v1{path}", headers=headers, **kwargs)
        if expected is not None:
            codes = expected if isinstance(expected, tuple) else (expected,)
            assert response.status_code in codes, (
                f"{method} {path} -> {response.status_code}: {response.text}"
            )
        return response

    async def get(self, path: str, **kw: Any) -> Any:
        return (await self.request("GET", path, expected=kw.pop("expected", 200), **kw)).json()

    async def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        response = await self.request(
            "POST", path, json=json, expected=kw.pop("expected", (200, 201, 202, 204)), **kw
        )
        return response.json() if response.content else None

    async def patch(self, path: str, json: Any, **kw: Any) -> Any:
        return (await self.request("PATCH", path, json=json, expected=kw.pop("expected", 200), **kw)).json()

    async def aclose(self) -> None:
        await self.http.aclose()


@pytest.fixture
async def client_factory(app: Any) -> AsyncIterator[Callable[[], ApiClient]]:
    clients: list[ApiClient] = []

    def make() -> ApiClient:
        c = ApiClient(app)
        clients.append(c)
        return c

    yield make
    for c in clients:
        await c.aclose()


async def drain_events() -> int:
    """Relay every outbox event through the in-process dispatcher (what the worker does without Kafka)."""
    consumers = all_consumers()

    async def publish(topic: str, _key: str, envelope: dict[str, Any]) -> None:
        parsed = EventEnvelope.model_validate(envelope)
        for consumer in consumers:
            if topic in consumer.topics:
                await process_event(consumer, parsed)

    from app.db.session import get_sessionmaker

    total = 0
    for _ in range(20):  # handlers may emit follow-up events (e.g. notification -> email)
        async with get_sessionmaker()() as session:
            published = await relay_batch(session, publish, batch_size=500)
        total += published
        if not published:
            break
    return total


TOKEN_RE = re.compile(r"token=([A-Za-z0-9_\-]+)")


def extract_token(mail: Any, path: str) -> str:
    for message in reversed(mail.sent):
        body = f"{message.text}\n{message.html}"
        if path in body:
            match = TOKEN_RE.search(body)
            if match:
                return match.group(1)
    raise AssertionError(f"No email containing {path} was captured")


async def register(
    client: ApiClient, name: str | None = None, password: str = "Str0ng-passphrase!"
) -> dict[str, Any]:
    handle = name or f"user{uuid.uuid4().hex[:8]}"
    me = await client.post(
        "/auth/register",
        {
            "email": f"{handle}@example.com",
            "password": password,
            "username": handle,
            "display_name": handle.title(),
        },
        expected=201,
    )
    client.me = me
    return me


async def verify_email(client: ApiClient, mail: Any) -> None:
    await drain_events()
    token = extract_token(mail, "/verify-email")
    await client.post("/auth/verify-email", {"token": token})


def sign_xdr(xdr: str, address: str) -> str:
    envelope = TransactionEnvelope.from_xdr(xdr, get_network().passphrase)
    envelope.sign(KEYRING[address])
    return envelope.to_xdr()


async def link_wallet(client: ApiClient, keypair: Keypair | None = None) -> str:
    """Proves ownership of a fresh (or given) keypair through the real SEP-10 challenge flow."""
    kp = keypair or Keypair.random()
    KEYRING[kp.public_key] = kp
    challenge = await client.post("/wallets/challenge", {"public_address": kp.public_key})
    wallet = await client.post(
        "/wallets/verify",
        {
            "public_address": kp.public_key,
            "signed_challenge_xdr": sign_xdr(challenge["challenge_xdr"], kp.public_key),
        },
    )
    assert wallet["verification_status"] == "VERIFIED"
    return kp.public_key


async def chain_action(client: ApiClient, prepare_path: str, body: dict[str, Any]) -> dict[str, Any]:
    """prepare -> sign the returned XDR with the wallet's keypair -> submit -> poll until CONFIRMED."""
    prepared = await client.post(prepare_path, body)
    assert prepared["unsigned_xdr"]
    signed = sign_xdr(prepared["unsigned_xdr"], body["wallet_address"])
    tx = await client.post(f"/transactions/{prepared['transaction']['id']}/submit", {"signed_xdr": signed})
    tx = await client.get(f"/transactions/{tx['id']}")
    assert tx["status"] == "CONFIRMED", tx
    assert tx["explorer_url"] == f"https://stellar.expert/explorer/testnet/tx/{tx['transaction_hash']}"
    return tx


def bounty_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "title": "Implement escrow status widget",
        "short_description": "Build a compact widget that shows escrow funding progress for a bounty.",
        "description": "A detailed description of the escrow status widget with clear scope and requirements.",
        "category": "DEVELOPMENT",
        "difficulty": "INTERMEDIATE",
        "reward_amount": "25.5",
        "positions_available": 1,
        "tags": ["frontend", "widget"],
        "required_skills": ["react", "typescript"],
    }
    payload.update(overrides)
    return payload


Setup = Callable[..., Awaitable[Any]]
