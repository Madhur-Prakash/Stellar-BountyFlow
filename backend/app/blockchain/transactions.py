"""Chain adapter interface and the real Stellar Testnet/Mainnet adapter.

Flow: the backend *prepares* (builds + simulates) a contract invocation whose source account is the user's
verified wallet, the wallet signs it in the browser, the backend verifies the signed envelope matches what was
prepared, submits it, then independently polls the network until it is confirmed or failed.

A contract account (a passkey smart wallet, ``C...``) cannot be a transaction source. Its invocations are
prepared with the platform sponsor as the source; the wallet signs only its Soroban authorization entries and
``relay`` re-simulates them (which runs the wallet's ``__check_auth``) into a sponsor-signed envelope. Eligible
user-signed transactions can also be sent inside a sponsor-paid fee bump (see ``app/blockchain/sponsorship.py``).
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from stellar_sdk import (
    Account,
    Address,
    FeeBumpTransactionEnvelope,
    Keypair,
    StrKey,
    TransactionBuilder,
    TransactionEnvelope,
    scval,
)
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.auth import _get_address_credentials
from stellar_sdk.exceptions import (
    BadResponseError,
    NotFoundError,
    PrepareTransactionException,
    SorobanRpcErrorResponse,
)
from stellar_sdk.exceptions import (
    ConnectionError as StellarConnectionError,
)
from stellar_sdk.operation import InvokeHostFunction
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
from app.cache.keys import PREFIX
from app.cache.redis import get_redis
from app.core.logging import get_logger

logger = get_logger(__name__)

# Ledgers close about every 5 seconds.
LEDGER_SECONDS = 5


class ChainUnavailable(Exception):
    """Transient: RPC timeout / network failure. Safe to retry."""


class ChainRejected(Exception):
    """Permanent rejection of a submission (bad sequence, expired, bad auth...)."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class AccountNotFound(Exception):
    pass


class SponsorRequired(ChainUnavailable):
    """A smart-wallet transaction needs the platform sponsor as its source, and none is configured."""


@dataclass(frozen=True)
class PreparedCall:
    unsigned_xdr: str | None
    tx_hash: str
    fee_stroops: int | None
    expires_at: datetime


@dataclass(frozen=True)
class RelayedCall:
    """A sponsor-sourced envelope carrying a contract account's signed authorization entries."""

    signed_xdr: str
    tx_hash: str
    fee_stroops: int
    sequence: int


@dataclass(frozen=True)
class TxOutcome:
    status: Literal["PENDING", "SUCCESS", "FAILED", "NOT_FOUND"]
    ledger: int | None = None
    ledger_close_time: datetime | None = None
    failure_reason: str | None = None
    result_code: str | None = None
    return_value: Any = None
    fee_charged: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ChainAdapter(Protocol):
    network: NetworkConfig

    async def prepare(self, call: ContractCall, source: str) -> PreparedCall: ...

    async def submit(self, signed_xdr: str, expected_hash: str) -> str: ...

    async def get_outcome(self, tx_hash: str) -> TxOutcome: ...

    async def read_escrow(self, bid: bytes, contract_id: str | None = None) -> EscrowSnapshot | None: ...

    async def read_assignment(
        self, bid: bytes, contributor: str, contract_id: str | None = None
    ) -> str | None: ...

    async def read(self, call: ContractCall) -> Any: ...

    async def relay(
        self,
        host_function: stellar_xdr.HostFunction,
        auth: list[stellar_xdr.SorobanAuthorizationEntry],
        sponsor: Keypair,
        max_fee: int,
    ) -> RelayedCall: ...

    async def native_balance(self, address: str) -> int | None: ...

    async def contract_wasm_hash(self, contract_id: str) -> str | None: ...

    async def latest_ledger(self) -> int: ...


def _now() -> datetime:
    return datetime.now(UTC)


def is_contract_address(address: str | None) -> bool:
    return bool(address) and StrKey.is_valid_contract(address or "")


def envelope_hashes(xdr: str, passphrase: str) -> tuple[str, str | None]:
    """``(hash sent to the network, inner hash)`` of an envelope; the inner hash is None unless it is a fee bump."""
    if FeeBumpTransactionEnvelope.is_fee_bump_transaction_envelope(xdr):
        bump = FeeBumpTransactionEnvelope.from_xdr(xdr, passphrase)
        return bump.hash_hex(), bump.transaction.inner_transaction_envelope.hash_hex()
    return TransactionEnvelope.from_xdr(xdr, passphrase).hash_hex(), None


def _sequence_key(address: str) -> str:
    return f"{PREFIX}:sponsor:seq:{address}"


def _sequence_lock(address: str) -> str:
    return f"{PREFIX}:lock:sponsor-seq:{address}"


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
        # A bounty's escrow may live on an earlier deployment (call.contract_id); new ones use the configured id.
        contract_id = call.contract_id or self._require_contract()
        if is_contract_address(source):
            return await self._prepare_for_contract_account(call, source, contract_id)
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

    async def _prepare_for_contract_account(
        self, call: ContractCall, source: str, contract_id: str
    ) -> PreparedCall:
        """The sponsor sources the envelope; the smart wallet only signs the returned authorization entries.

        Simulation records the entries with address-bound (CAP-71) credentials, which is what passkey wallets
        sign. Each entry for the wallet gets a signature expiration covering the transaction timeout, so the
        wallet signs a bounded authorization. The resource fees are re-estimated in ``relay`` once the entries
        are signed (the wallet's ``__check_auth`` only runs then)."""
        from app.blockchain.sponsorship import sponsor_keypair

        sponsor = sponsor_keypair()
        if sponsor is None:
            raise SponsorRequired(
                "Smart-wallet transactions need the platform fee sponsor, which is not configured on this "
                "server (STELLAR_SPONSOR_SECRET)."
            )
        server = get_soroban()
        account = await self._rpc(server.load_account(sponsor.public_key))
        tx = (
            TransactionBuilder(account, self.network.passphrase, base_fee=self.network.base_fee)
            .append_invoke_contract_function_op(contract_id, call.function, call.args)
            .set_timeout(self.network.tx_timeout_seconds)
            .build()
        )
        simulation = await self._rpc(server.simulate_transaction(tx, use_upgraded_auth=True))
        if simulation.error:
            raise soroban.parse_contract_error(simulation.error)
        try:
            prepared = await self._rpc(server.prepare_transaction(tx, simulation, use_upgraded_auth=True))
        except PrepareTransactionException as exc:
            raise soroban.parse_contract_error(str(exc.simulate_transaction_response.error)) from exc
        valid_until = (
            simulation.latest_ledger + math.ceil(self.network.tx_timeout_seconds / LEDGER_SECONDS) + 2
        )
        op = prepared.transaction.operations[0]
        assert isinstance(op, InvokeHostFunction)
        for entry in op.auth:
            credentials = _get_address_credentials(entry.credentials)
            if credentials is not None:
                credentials.signature_expiration_ledger = stellar_xdr.Uint32(valid_until)
        return PreparedCall(
            unsigned_xdr=prepared.to_xdr(),
            tx_hash=prepared.hash_hex(),
            fee_stroops=prepared.transaction.fee,
            expires_at=_now() + timedelta(seconds=self.network.tx_timeout_seconds),
        )

    async def submit(self, signed_xdr: str, expected_hash: str) -> str:
        """Sends an envelope. For a fee bump the returned hash is the inner transaction's (the one BountyFlow
        prepared and tracks; RPC and Horizon find a fee bump by either hash)."""
        sent_hash, inner_hash = envelope_hashes(signed_xdr, self.network.passphrase)
        response = await self._rpc(get_soroban().send_transaction(signed_xdr))
        if response.status in (SendTransactionStatus.PENDING, SendTransactionStatus.DUPLICATE):
            if inner_hash is not None and str(response.hash) == sent_hash:
                return inner_hash
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
        fee_charged = _fee_charged(response.result_xdr)
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
                fee_charged=fee_charged,
                metadata={"application_order": response.application_order},
            )
        code = decode_tx_result_code(response.result_xdr)
        return TxOutcome(
            status="FAILED",
            ledger=response.ledger,
            result_code=code,
            failure_reason=describe_result_code(code),
            fee_charged=fee_charged,
        )

    async def _read(self, call: ContractCall) -> Any:
        contract_id = call.contract_id or self._require_contract()
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

    async def read_escrow(self, bid: bytes, contract_id: str | None = None) -> EscrowSnapshot | None:
        try:
            native = await self._read(soroban.on_contract(soroban.get_escrow(bid), contract_id))
        except ContractError as exc:
            if exc.code == 1:  # NotFound
                return None
            raise
        return soroban.decode_escrow(native) if isinstance(native, dict) else None

    async def read_assignment(
        self, bid: bytes, contributor: str, contract_id: str | None = None
    ) -> str | None:
        call = soroban.on_contract(soroban.assignment(bid, contributor), contract_id)
        return soroban.decode_assignment(await self._read(call))

    async def read(self, call: ContractCall) -> Any:
        """Any read-only contract view (e.g. v2 ``review`` / ``resolution_votes``), as native Python values."""
        return await self._read(call)

    # --- Sponsored submission ---------------------------------------------------------------------

    async def relay(
        self,
        host_function: stellar_xdr.HostFunction,
        auth: list[stellar_xdr.SorobanAuthorizationEntry],
        sponsor: Keypair,
        max_fee: int,
    ) -> RelayedCall:
        """Builds the sponsor-sourced envelope for signed authorization entries and signs it.

        The simulation runs in enforcing mode (the entries are signed), so a wrong or missing wallet signature
        fails here as a contract error, before anything reaches the network. Sequence numbers of the shared
        sponsor account are reserved in Redis so concurrent relays do not collide."""
        server = get_soroban()
        lock = _sequence_lock(sponsor.public_key)
        locked = await _acquire(lock)
        try:
            account = await self._rpc(server.load_account(sponsor.public_key))
            reserved = await _reserved_sequence(sponsor.public_key)
            if reserved is not None and reserved > account.sequence:
                account = Account(sponsor.public_key, reserved)
            tx = (
                TransactionBuilder(account, self.network.passphrase, base_fee=self.network.base_fee)
                .append_operation(InvokeHostFunction(host_function=host_function, auth=auth))
                .set_timeout(self.network.tx_timeout_seconds)
                .build()
            )
            simulation = await self._rpc(server.simulate_transaction(tx))
            if simulation.error:
                raise soroban.parse_contract_error(simulation.error)
            try:
                prepared = await self._rpc(server.prepare_transaction(tx, simulation))
            except PrepareTransactionException as exc:
                raise soroban.parse_contract_error(str(exc.simulate_transaction_response.error)) from exc
            fee = prepared.transaction.fee
            if fee > max_fee:
                raise ContractError(
                    None,
                    f"The network fee ({fee} stroops) is above the sponsorship limit ({max_fee} stroops).",
                )
            prepared.sign(sponsor)
            sequence = prepared.transaction.sequence
            await _reserve_sequence(sponsor.public_key, sequence)
            return RelayedCall(
                signed_xdr=prepared.to_xdr(), tx_hash=prepared.hash_hex(), fee_stroops=fee, sequence=sequence
            )
        finally:
            if locked:
                await _release(lock)

    async def native_balance(self, address: str) -> int | None:
        """The account's XLM balance in stroops, or None when the account does not exist."""
        key = stellar_xdr.LedgerKey(
            type=stellar_xdr.LedgerEntryType.ACCOUNT,
            account=stellar_xdr.LedgerKeyAccount(
                account_id=Keypair.from_public_key(address).xdr_account_id()
            ),
        )
        response = await self._rpc(get_soroban().get_ledger_entries([key]))
        if not response.entries:
            return None
        data = stellar_xdr.LedgerEntryData.from_xdr(response.entries[0].xdr)
        assert data.account is not None
        return int(data.account.balance.int64)

    async def contract_wasm_hash(self, contract_id: str) -> str | None:
        """The WASM hash a contract instance runs, or None when the contract does not exist."""
        key = stellar_xdr.LedgerKey(
            type=stellar_xdr.LedgerEntryType.CONTRACT_DATA,
            contract_data=stellar_xdr.LedgerKeyContractData(
                contract=Address(contract_id).to_xdr_sc_address(),
                key=stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_LEDGER_KEY_CONTRACT_INSTANCE),
                durability=stellar_xdr.ContractDataDurability.PERSISTENT,
            ),
        )
        response = await self._rpc(get_soroban().get_ledger_entries([key]))
        if not response.entries:
            return None
        data = stellar_xdr.LedgerEntryData.from_xdr(response.entries[0].xdr)
        assert data.contract_data is not None
        instance = data.contract_data.val.instance
        if instance is None or instance.executable.wasm_hash is None:
            return None
        return instance.executable.wasm_hash.hash.hex()

    async def latest_ledger(self) -> int:
        return int((await self._rpc(get_soroban().get_latest_ledger())).sequence)


def _fee_charged(result_xdr: str | None) -> int | None:
    if not result_xdr:
        return None
    try:
        return int(stellar_xdr.TransactionResult.from_xdr(result_xdr).fee_charged.int64)
    except Exception:
        return None


async def _acquire(key: str, ttl: int = 30) -> bool:
    try:
        for _ in range(50):
            if await get_redis().set(key, "1", nx=True, ex=ttl):
                return True
            await asyncio.sleep(0.2)
    except Exception:
        return False  # Redis down: the network still rejects a reused sequence (txBAD_SEQ)
    return False


async def _release(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception:  # noqa: S110
        pass


async def _reserved_sequence(address: str) -> int | None:
    try:
        raw = await get_redis().get(_sequence_key(address))
    except Exception:
        return None
    return int(raw) if raw else None


async def _reserve_sequence(address: str, sequence: int) -> None:
    try:
        # Long enough for the relayed transaction to be included; after that the ledger value is current again.
        await get_redis().set(_sequence_key(address), str(sequence), ex=120)
    except Exception:  # noqa: S110
        pass


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
