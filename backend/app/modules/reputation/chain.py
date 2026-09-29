"""The attestation registry contract (contracts/attestations): call encoding, record decoding and the adapter.

Unlike escrow actions, which the user's wallet signs, attestations are signed by the platform's attester key
(``STELLAR_ATTESTER_SECRET``) and submitted by the server. Every attester transaction takes a Redis lock and
waits for its outcome before releasing it, so two submissions never race on the attester's sequence number.
Reads are simulations and sign nothing.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol

from stellar_sdk import Account, Address, Keypair, TransactionBuilder, scval
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.exceptions import NotFoundError, PrepareTransactionException
from stellar_sdk.soroban_rpc import SendTransactionStatus

from app.blockchain.client import get_soroban
from app.blockchain.config import NetworkConfig, get_network
from app.blockchain.transactions import ChainRejected, ChainUnavailable, StellarAdapter, TxOutcome
from app.blockchain.verification import decode_tx_result_code, describe_result_code
from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# contracts/attestations/src/errors.rs
ATTESTATION_ERRORS: dict[int, tuple[str, str]] = {
    1: ("NotFound", "The attestation does not exist on-chain."),
    2: ("AlreadyAttested", "This completion is already attested on-chain."),
    3: ("Unauthorized", "The configured key is not the registry's attester."),
    4: ("InvalidAmount", "The attested amount must be positive."),
    5: ("InvalidTimestamp", "The completion time must be in the past."),
    6: ("AlreadyRevoked", "The attestation is already revoked."),
    7: ("InvalidReason", "A revocation reason is 1 to 200 bytes."),
    8: ("InvalidContributor", "The attester cannot attest its own account."),
    9: ("Overflow", "Arithmetic overflow."),
}
# Errors that no retry can fix: the pipeline marks the row FAILED instead of retrying.
PERMANENT_ERRORS = frozenset({3, 4, 5, 7, 8, 9})

_CONTRACT_ERROR_RE = re.compile(r"Error\(Contract, #(\d+)\)")

LOCK_TTL_SECONDS = 90
OUTCOME_POLL_SECONDS = 2.0
OUTCOME_WAIT_SECONDS = 45.0
MAX_REASON_BYTES = 200


class AttestationError(Exception):
    """The registry refused a call (surfaced at simulation, before anything was signed or sent)."""

    def __init__(self, code: int | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.name = ATTESTATION_ERRORS.get(code, ("Unknown", ""))[0] if code else "Unknown"
        self.message = message

    @property
    def permanent(self) -> bool:
        return self.code in PERMANENT_ERRORS


def parse_error(raw: str) -> AttestationError:
    match = _CONTRACT_ERROR_RE.search(raw or "")
    if match:
        code = int(match.group(1))
        return AttestationError(code, ATTESTATION_ERRORS.get(code, ("", f"Contract error #{code}."))[1])
    if "balance" in (raw or "").lower():
        return AttestationError(None, "The attester account cannot pay the network fee.")
    return AttestationError(None, "The attestation registry rejected this call during simulation.")


@dataclass(frozen=True)
class AttestationConfig:
    network: NetworkConfig
    contract_id: str | None
    attester_secret: str | None

    @property
    def reads_enabled(self) -> bool:
        return bool(self.contract_id)

    @property
    def writes_enabled(self) -> bool:
        return self.reads_enabled and self.attester_address is not None

    @property
    def attester_address(self) -> str | None:
        return attester_address(self.attester_secret) if self.attester_secret else None

    def contract_url(self) -> str | None:
        if not self.contract_id:
            return None
        return f"{self.network.explorer_base_url.rstrip('/')}/contract/{self.contract_id}"


@lru_cache(maxsize=4)
def attester_address(secret: str) -> str | None:
    try:
        return Keypair.from_secret(secret).public_key
    except Exception:
        logger.error("attester_secret_invalid")
        return None


def get_config() -> AttestationConfig:
    settings = get_settings()
    return AttestationConfig(
        network=get_network(),
        contract_id=settings.attestation_contract_id or None,
        attester_secret=settings.stellar_attester_secret or None,
    )


@dataclass(frozen=True)
class Completion:
    """What an attestation records (the arguments of ``attest`` besides the attester)."""

    contributor: str
    bounty_id: bytes
    escrow_contract: str
    payout_tx: bytes
    token: str
    amount: int  # smallest token unit (stroops)
    completed_at: int  # unix seconds


@dataclass(frozen=True)
class OnchainAttestation:
    """Decoded ``Attestation`` struct."""

    id: int
    attester: str
    contributor: str
    bounty_id: str  # hex
    escrow_contract: str
    payout_tx: str  # hex
    token: str
    amount: int
    completed_at: int
    attested_at: int
    contributor_index: int
    revoked: bool
    revoked_at: int
    revocation_reason: str

    def matches(self, completion: Completion) -> bool:
        return (
            self.contributor == completion.contributor
            and self.bounty_id == completion.bounty_id.hex()
            and self.escrow_contract == completion.escrow_contract
            and self.payout_tx == completion.payout_tx.hex()
            and self.token == completion.token
            and self.amount == completion.amount
            and self.completed_at == completion.completed_at
        )

    @property
    def attested_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.attested_at, UTC)

    @property
    def revoked_datetime(self) -> datetime | None:
        return datetime.fromtimestamp(self.revoked_at, UTC) if self.revoked else None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _addr(value: Any) -> str:
    return value.address if isinstance(value, Address) else str(value)


def _hex(value: Any) -> str:
    return value.hex() if isinstance(value, bytes | bytearray) else str(value)


def _text(value: Any) -> str:
    return (
        value.decode("utf-8", errors="replace") if isinstance(value, bytes | bytearray) else str(value or "")
    )


def decode_attestation(native: dict[str, Any]) -> OnchainAttestation:
    return OnchainAttestation(
        id=int(native["id"]),
        attester=_addr(native["attester"]),
        contributor=_addr(native["contributor"]),
        bounty_id=_hex(native["bounty_id"]),
        escrow_contract=_addr(native["escrow_contract"]),
        payout_tx=_hex(native["payout_tx"]),
        token=_addr(native["token"]),
        amount=int(native["amount"]),
        completed_at=int(native["completed_at"]),
        attested_at=int(native["attested_at"]),
        contributor_index=int(native["contributor_index"]),
        revoked=bool(native["revoked"]),
        revoked_at=int(native["revoked_at"]),
        revocation_reason=_text(native["revocation_reason"]),
    )


def _bytes32(value: bytes) -> stellar_xdr.SCVal:
    assert len(value) == 32
    return scval.to_bytes(value)


def attest_args(attester: str, c: Completion) -> list[stellar_xdr.SCVal]:
    """Argument order matches ``attest`` in contracts/attestations/src/lib.rs exactly."""
    return [
        scval.to_address(attester),
        scval.to_address(c.contributor),
        _bytes32(c.bounty_id),
        scval.to_address(c.escrow_contract),
        _bytes32(c.payout_tx),
        scval.to_address(c.token),
        scval.to_int128(c.amount),
        scval.to_uint64(c.completed_at),
    ]


def revoke_args(attester: str, onchain_id: int, reason: str) -> list[stellar_xdr.SCVal]:
    return [scval.to_address(attester), scval.to_uint64(onchain_id), scval.to_string(reason)]


class AttestationChain(Protocol):
    config: AttestationConfig

    async def attest(self, completion: Completion) -> str: ...

    async def revoke(self, onchain_id: int, reason: str) -> str: ...

    async def wait_for_outcome(self, tx_hash: str, timeout: float = OUTCOME_WAIT_SECONDS) -> TxOutcome: ...

    async def get_outcome(self, tx_hash: str) -> TxOutcome: ...

    async def get(self, onchain_id: int) -> OnchainAttestation | None: ...

    async def find(
        self, bounty_id: bytes, contributor: str, payout_tx: bytes
    ) -> OnchainAttestation | None: ...

    async def count_by_contributor(self, contributor: str) -> int: ...


@asynccontextmanager
async def attester_lock() -> AsyncIterator[None]:
    """Serialises attester transactions across the API and worker processes. Best-effort without Redis: the
    contract still refuses duplicates, and a sequence conflict is retried."""
    key = keys.job_lock("attester-submit")
    token = str(id(asyncio.current_task()))
    acquired = False
    try:
        for _ in range(int(LOCK_TTL_SECONDS / OUTCOME_POLL_SECONDS)):
            try:
                acquired = bool(await get_redis().set(key, token, nx=True, ex=LOCK_TTL_SECONDS))
            except Exception:
                break  # Redis down: proceed unguarded
            if acquired:
                break
            await asyncio.sleep(OUTCOME_POLL_SECONDS)
        else:
            raise ChainUnavailable("Another attester transaction is still being confirmed.")
        yield
    finally:
        if acquired:
            try:
                await get_redis().delete(key)
            except Exception:  # noqa: S110
                pass


class StellarAttestationChain:
    """Real network adapter for the attestation registry."""

    def __init__(self, config: AttestationConfig) -> None:
        self.config = config
        self._outcomes = StellarAdapter(config.network)

    def _contract(self) -> str:
        if not self.config.contract_id:
            raise ChainUnavailable("The attestation registry is not configured (ATTESTATION_CONTRACT_ID).")
        return self.config.contract_id

    def _keypair(self) -> Keypair:
        if not self.config.attester_secret or not self.config.attester_address:
            raise ChainUnavailable("The attester key is not configured (STELLAR_ATTESTER_SECRET).")
        return Keypair.from_secret(self.config.attester_secret)

    async def _rpc(self, coro: Any) -> Any:
        return await self._outcomes._rpc(coro)

    async def _invoke(self, function: str, args: list[stellar_xdr.SCVal]) -> str:
        """Build, simulate, sign with the attester key and send. Returns the transaction hash."""
        contract_id = self._contract()
        keypair = self._keypair()
        server = get_soroban()
        network = self.config.network
        try:
            account = await self._rpc(server.load_account(keypair.public_key))
        except NotFoundError as exc:
            raise ChainUnavailable("The attester account does not exist on the network yet.") from exc
        tx = (
            TransactionBuilder(account, network.passphrase, base_fee=network.base_fee)
            .append_invoke_contract_function_op(contract_id, function, args)
            .set_timeout(network.tx_timeout_seconds)
            .build()
        )
        simulation = await self._rpc(server.simulate_transaction(tx))
        if simulation.error:
            raise parse_error(simulation.error)
        try:
            prepared = await self._rpc(server.prepare_transaction(tx, simulation))
        except PrepareTransactionException as exc:
            raise parse_error(str(exc.simulate_transaction_response.error)) from exc
        prepared.sign(keypair)
        response = await self._rpc(server.send_transaction(prepared))
        if response.status in (SendTransactionStatus.PENDING, SendTransactionStatus.DUPLICATE):
            return str(response.hash)
        if response.status == SendTransactionStatus.TRY_AGAIN_LATER:
            raise ChainUnavailable("The network is busy. The attestation will be retried.")
        code = decode_tx_result_code(response.error_result_xdr)
        raise ChainRejected(describe_result_code(code), code)

    async def attest(self, completion: Completion) -> str:
        return await self._invoke("attest", attest_args(self._keypair().public_key, completion))

    async def revoke(self, onchain_id: int, reason: str) -> str:
        return await self._invoke("revoke", revoke_args(self._keypair().public_key, onchain_id, reason))

    async def get_outcome(self, tx_hash: str) -> TxOutcome:
        return await self._outcomes.get_outcome(tx_hash)

    async def wait_for_outcome(self, tx_hash: str, timeout: float = OUTCOME_WAIT_SECONDS) -> TxOutcome:
        """Polls until the network settles the transaction (or ``timeout``; then the last outcome is returned)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            outcome = await self.get_outcome(tx_hash)
            if outcome.status in ("SUCCESS", "FAILED") or loop.time() >= deadline:
                return outcome
            await asyncio.sleep(OUTCOME_POLL_SECONDS)

    async def _read(self, function: str, args: list[stellar_xdr.SCVal]) -> Any:
        contract_id = self._contract()
        network = self.config.network
        # Read-only simulation: the source account is irrelevant and never signs anything.
        reader = self.config.attester_address or Keypair.random().public_key
        tx = (
            TransactionBuilder(Account(reader, 0), network.passphrase, base_fee=network.base_fee)
            .append_invoke_contract_function_op(contract_id, function, args)
            .set_timeout(60)
            .build()
        )
        simulation = await self._rpc(get_soroban().simulate_transaction(tx))
        if simulation.error:
            raise parse_error(simulation.error)
        if not simulation.results:
            return None
        return scval.to_native(simulation.results[0].xdr)

    async def get(self, onchain_id: int) -> OnchainAttestation | None:
        try:
            native = await self._read("get", [scval.to_uint64(onchain_id)])
        except AttestationError as exc:
            if exc.code == 1:  # NotFound
                return None
            raise
        return decode_attestation(native) if isinstance(native, dict) else None

    async def find(self, bounty_id: bytes, contributor: str, payout_tx: bytes) -> OnchainAttestation | None:
        native = await self._read(
            "find", [_bytes32(bounty_id), scval.to_address(contributor), _bytes32(payout_tx)]
        )
        return decode_attestation(native) if isinstance(native, dict) else None

    async def count_by_contributor(self, contributor: str) -> int:
        return int(await self._read("count_by_contributor", [scval.to_address(contributor)]) or 0)


_chain: AttestationChain | None = None


def get_chain() -> AttestationChain:
    global _chain
    if _chain is None:
        _chain = StellarAttestationChain(get_config())
    return _chain


def set_chain(chain: AttestationChain | None) -> None:
    """Tests inject a test double here; the application only ever uses StellarAttestationChain."""
    global _chain
    _chain = chain
