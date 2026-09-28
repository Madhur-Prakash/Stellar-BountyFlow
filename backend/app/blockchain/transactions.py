"""Chain adapter interface and the real Stellar Testnet/Mainnet adapter.

Flow: the backend *prepares* (builds + simulates) a contract invocation whose source account is the user's
verified wallet, the wallet signs it in the browser, the backend verifies the signed envelope matches what was
prepared, submits it, then independently polls the network until it is confirmed or failed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from stellar_sdk import Account, Keypair, TransactionBuilder, scval
from stellar_sdk.exceptions import (
    BadResponseError,
    NotFoundError,
    PrepareTransactionException,
    SorobanRpcErrorResponse,
)
from stellar_sdk.exceptions import (
    ConnectionError as StellarConnectionError,
)
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus

from app.blockchain import soroban
from app.blockchain.client import get_soroban
from app.blockchain.config import NetworkConfig, get_network
from app.blockchain.soroban import ContractCall, ContractError, EscrowSnapshot
from app.blockchain.verification import (
    decode_tx_result_code,
    describe_result_code,
    extract_return_value,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChainUnavailable(Exception):
    """Transient: RPC timeout / network failure. Safe to retry."""


class ChainRejected(Exception):
    """Permanent rejection of a submission (bad sequence, expired, bad auth...)."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class AccountNotFound(Exception):
    pass


@dataclass(frozen=True)
class PreparedCall:
    unsigned_xdr: str | None
    tx_hash: str
    fee_stroops: int | None
    expires_at: datetime


@dataclass(frozen=True)
class TxOutcome:
    status: Literal["PENDING", "SUCCESS", "FAILED", "NOT_FOUND"]
    ledger: int | None = None
    ledger_close_time: datetime | None = None
    failure_reason: str | None = None
    result_code: str | None = None
    return_value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChainAdapter(Protocol):
    network: NetworkConfig

    async def prepare(self, call: ContractCall, source: str) -> PreparedCall: ...

    async def submit(self, signed_xdr: str, expected_hash: str) -> str: ...

    async def get_outcome(self, tx_hash: str) -> TxOutcome: ...

    async def read_escrow(self, bid: bytes) -> EscrowSnapshot | None: ...

    async def read_assignment(self, bid: bytes, contributor: str) -> str | None: ...


def _now() -> datetime:
    return datetime.now(UTC)


class StellarAdapter:
    """Real network adapter (Testnet by default)."""

    def __init__(self, network: NetworkConfig) -> None:
        self.network = network

    def _require_contract(self) -> str:
        if not self.network.contract_id or not self.network.native_asset_contract_id:
            raise ChainUnavailable(
                "The escrow contract is not configured. Set SOROBAN_CONTRACT_ID and "
                "STELLAR_NATIVE_ASSET_CONTRACT_ID (run `make contract-deploy-testnet`)."
            )
        return self.network.contract_id

    async def _rpc(self, coro: Any) -> Any:
        try:
            async with asyncio.timeout(self.network.rpc_timeout_seconds + 2):
                return await coro
        except TimeoutError as exc:
            raise ChainUnavailable("The Stellar RPC timed out. Please try again.") from exc
        except (StellarConnectionError, BadResponseError) as exc:
            raise ChainUnavailable(f"Could not reach the Stellar RPC: {exc}") from exc
        except SorobanRpcErrorResponse as exc:
            raise ChainUnavailable(f"Stellar RPC error: {exc.message}") from exc

    async def prepare(self, call: ContractCall, source: str) -> PreparedCall:
        contract_id = self._require_contract()
        server = get_soroban()
        try:
            account = await self._rpc(server.load_account(source))
        except NotFoundError as exc:
            raise AccountNotFound(
                "This wallet account does not exist on the network yet. Fund it first "
                "(on Testnet use Friendbot: https://friendbot.stellar.org/?addr=<address>)."
            ) from exc
        tx = (
            TransactionBuilder(account, self.network.passphrase, base_fee=self.network.base_fee)
            .append_invoke_contract_function_op(contract_id, call.function, call.args)
            .set_timeout(self.network.tx_timeout_seconds)
            .build()
        )
        simulation = await self._rpc(server.simulate_transaction(tx, use_upgraded_auth=False))
        if simulation.error:
            raise soroban.parse_contract_error(simulation.error)
        try:
            prepared = await self._rpc(server.prepare_transaction(tx, simulation))
        except PrepareTransactionException as exc:
            raise soroban.parse_contract_error(str(exc.simulate_transaction_response.error)) from exc
        return PreparedCall(
            unsigned_xdr=prepared.to_xdr(),
            tx_hash=prepared.hash_hex(),
            fee_stroops=prepared.transaction.fee,
            expires_at=_now() + timedelta(seconds=self.network.tx_timeout_seconds),
        )

    async def submit(self, signed_xdr: str, expected_hash: str) -> str:
        response = await self._rpc(get_soroban().send_transaction(signed_xdr))
        if response.status in (SendTransactionStatus.PENDING, SendTransactionStatus.DUPLICATE):
            return str(response.hash)
        if response.status == SendTransactionStatus.TRY_AGAIN_LATER:
            raise ChainUnavailable("The network is busy. Please try submitting again shortly.")
        code = decode_tx_result_code(response.error_result_xdr)
        raise ChainRejected(describe_result_code(code), code)

    async def get_outcome(self, tx_hash: str) -> TxOutcome:
        response = await self._rpc(get_soroban().get_transaction(tx_hash))
        if response.status == GetTransactionStatus.NOT_FOUND:
            return TxOutcome(status="NOT_FOUND")
        close_time = datetime.fromtimestamp(int(response.create_at), UTC) if response.create_at else None
        if response.status == GetTransactionStatus.SUCCESS:
            return_value = extract_return_value(response.result_meta_xdr)
            native: Any = None
            if return_value is not None:
                try:
                    native = scval.to_native(return_value)
                except Exception:
                    native = None
            return TxOutcome(
                status="SUCCESS",
                ledger=response.ledger,
                ledger_close_time=close_time or _now(),
                return_value=native,
                metadata={"application_order": response.application_order},
            )
        code = decode_tx_result_code(response.result_xdr)
        return TxOutcome(
            status="FAILED",
            ledger=response.ledger,
            result_code=code,
            failure_reason=describe_result_code(code),
        )

    async def _read(self, call: ContractCall) -> Any:
        contract_id = self._require_contract()
        # Read-only simulation: the source account is irrelevant and never signs anything.
        reader = self.network.arbiter_address or Keypair.random().public_key
        tx = (
            TransactionBuilder(Account(reader, 0), self.network.passphrase, base_fee=self.network.base_fee)
            .append_invoke_contract_function_op(contract_id, call.function, call.args)
            .set_timeout(60)
            .build()
        )
        simulation = await self._rpc(get_soroban().simulate_transaction(tx))
        if simulation.error:
            raise soroban.parse_contract_error(simulation.error)
        if not simulation.results:
            return None
        return scval.to_native(simulation.results[0].xdr)

    async def read_escrow(self, bid: bytes) -> EscrowSnapshot | None:
        try:
            native = await self._read(soroban.get_escrow(bid))
        except ContractError as exc:
            if exc.code == 1:  # NotFound
                return None
            raise
        return soroban.decode_escrow(native) if isinstance(native, dict) else None

    async def read_assignment(self, bid: bytes, contributor: str) -> str | None:
        return soroban.decode_assignment(await self._read(soroban.assignment(bid, contributor)))


_adapter: ChainAdapter | None = None


def get_adapter() -> ChainAdapter:
    global _adapter
    if _adapter is None:
        _adapter = StellarAdapter(get_network())
    return _adapter


def set_adapter(adapter: ChainAdapter | None) -> None:
    """Tests inject a test double here; the application only ever uses StellarAdapter."""
    global _adapter
    _adapter = adapter
