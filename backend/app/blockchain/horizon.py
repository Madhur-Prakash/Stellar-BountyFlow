"""Horizon reads for balances and trustlines, and submission of classic transactions (``changeTrust``).

Soroban RPC answers contract questions; Horizon answers account questions: which assets an account holds, whether
it has a trustline for an asset (a SAC transfer of a classic asset to a G-address without one fails), how much it
can spend after reserves and open offers, and the issuer's authorization flags. Reads are made through
``get_horizon()`` so tests can inject a test double, like ``transactions.set_adapter``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from stellar_sdk import ServerAsync, TransactionEnvelope
from stellar_sdk.client.aiohttp_client import AiohttpClient
from stellar_sdk.exceptions import BadRequestError, BadResponseError, NotFoundError
from stellar_sdk.exceptions import ConnectionError as StellarConnectionError

from app.blockchain.assets import NATIVE
from app.blockchain.config import NetworkConfig, get_network
from app.core.logging import get_logger

logger = get_logger(__name__)

# Stellar's base reserve: every account keeps (2 + subentries) × 0.5 XLM that it cannot spend.
BASE_RESERVE = Decimal("0.5")
ZERO = Decimal(0)

# Horizon result codes (snake_case, as Horizon reports them) → what the wallet owner should do.
RESULT_MESSAGES: dict[str, str] = {
    "tx_bad_seq": "Another transaction from this wallet landed first. Please try again.",
    "tx_too_late": "The transaction expired before it was submitted. Please start again.",
    "tx_insufficient_balance": "The wallet does not have enough XLM to pay the network fee.",
    "tx_insufficient_fee": "The network fee was too low. Please try again.",
    "tx_bad_auth": "The transaction signature is invalid or missing.",
    "tx_no_source_account": "This wallet account does not exist on the network yet.",
    "op_low_reserve": "The wallet needs 0.5 XLM more to cover the reserve for a new trustline.",
    "op_no_issuer": "The asset's issuer account does not exist on this network.",
    "op_invalid_limit": "The trustline limit is below the wallet's current balance of this asset.",
    "op_malformed": "The trustline operation is malformed.",
}


class HorizonUnavailable(Exception):
    """Transient: Horizon timed out or could not be reached. The outcome is unknown."""


@dataclass(frozen=True)
class AssetBalance:
    identifier: str
    balance: Decimal
    limit: Decimal | None = None  # None for XLM
    buying_liabilities: Decimal = ZERO
    selling_liabilities: Decimal = ZERO
    is_authorized: bool = True

    @property
    def spendable(self) -> Decimal:
        """What the account can send now: its balance minus amounts locked in open offers."""
        return max(ZERO, self.balance - self.selling_liabilities)


@dataclass(frozen=True)
class AccountState:
    address: str
    sequence: int
    balances: dict[str, AssetBalance]
    subentry_count: int = 0
    num_sponsoring: int = 0
    num_sponsored: int = 0
    flags: dict[str, bool] = field(default_factory=dict)

    def balance(self, identifier: str) -> AssetBalance | None:
        return self.balances.get(identifier)

    @property
    def minimum_balance(self) -> Decimal:
        entries = 2 + self.subentry_count + self.num_sponsoring - self.num_sponsored
        return BASE_RESERVE * max(entries, 0)

    @property
    def native_spendable(self) -> Decimal:
        """XLM the account can send now: balance minus its reserve and XLM locked in open offers."""
        native = self.balances.get(NATIVE)
        if native is None:
            return ZERO
        return max(ZERO, native.balance - self.minimum_balance - native.selling_liabilities)


@dataclass(frozen=True)
class ClassicResult:
    """Outcome of a classic transaction on Horizon."""

    tx_hash: str
    successful: bool
    ledger: int | None = None
    result_code: str | None = None
    message: str | None = None


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def parse_account(record: dict[str, Any]) -> AccountState:
    """Horizon ``/accounts/{id}`` record → ``AccountState``. Liquidity pool shares are ignored."""
    balances: dict[str, AssetBalance] = {}
    for row in record.get("balances") or []:
        asset_type = row.get("asset_type")
        if asset_type == "native":
            identifier = NATIVE
        elif asset_type in ("credit_alphanum4", "credit_alphanum12"):
            identifier = f"{row.get('asset_code')}:{row.get('asset_issuer')}"
        else:
            continue
        balances[identifier] = AssetBalance(
            identifier=identifier,
            balance=_dec(row.get("balance")),
            limit=_dec(row["limit"]) if row.get("limit") is not None else None,
            buying_liabilities=_dec(row.get("buying_liabilities", 0)),
            selling_liabilities=_dec(row.get("selling_liabilities", 0)),
            is_authorized=bool(row.get("is_authorized", True)),
        )
    flags = record.get("flags") or {}
    return AccountState(
        address=str(record.get("account_id") or record.get("id")),
        sequence=int(record.get("sequence") or 0),
        balances=balances,
        subentry_count=int(record.get("subentry_count") or 0),
        num_sponsoring=int(record.get("num_sponsoring") or 0),
        num_sponsored=int(record.get("num_sponsored") or 0),
        flags={k: bool(v) for k, v in flags.items()},
    )


def result_codes(extras: dict[str, Any] | None) -> tuple[str | None, list[str]]:
    codes = (extras or {}).get("result_codes") or {}
    return codes.get("transaction"), list(codes.get("operations") or [])


def describe_codes(tx_code: str | None, op_codes: list[str]) -> tuple[str, str]:
    """(most specific code, human message) for a failed classic transaction."""
    for code in [*op_codes, tx_code]:
        if code and code in RESULT_MESSAGES:
            return code, RESULT_MESSAGES[code]
    code = next((c for c in [*op_codes, tx_code] if c and c != "op_success"), None) or "tx_failed"
    return code, f"The transaction failed ({code})."


class HorizonGateway(Protocol):
    network: NetworkConfig

    async def load_account(self, address: str) -> AccountState | None: ...

    async def submit(self, signed_xdr: str) -> ClassicResult: ...

    async def transaction(self, tx_hash: str) -> ClassicResult | None: ...


class HorizonClient:
    """Real Horizon client for the configured network."""

    def __init__(self, network: NetworkConfig) -> None:
        self.network = network
        self._server: ServerAsync | None = None

    def _get(self) -> ServerAsync:
        if self._server is None:
            http = AiohttpClient(
                pool_size=10,
                request_timeout=self.network.rpc_timeout_seconds,
                post_timeout=max(
                    self.network.rpc_timeout_seconds, 35.0
                ),  # Horizon waits up to 30 s on submit
                user_agent="bountyflow-api",
            )
            self._server = ServerAsync(self.network.horizon_url, client=http)
        return self._server

    async def _call(self, coro: Any, timeout: float | None = None) -> Any:
        try:
            async with asyncio.timeout(timeout or self.network.rpc_timeout_seconds + 2):
                return await coro
        except TimeoutError as exc:
            raise HorizonUnavailable("Horizon timed out. Please try again.") from exc
        except (StellarConnectionError, BadResponseError) as exc:
            raise HorizonUnavailable(f"Could not reach Horizon: {exc}") from exc

    async def load_account(self, address: str) -> AccountState | None:
        try:
            record = await self._call(self._get().accounts().account_id(address).call())
        except NotFoundError:
            return None
        return parse_account(record)

    async def submit(self, signed_xdr: str) -> ClassicResult:
        tx_hash = TransactionEnvelope.from_xdr(signed_xdr, self.network.passphrase).hash_hex()
        try:
            response = await self._call(
                self._get().submit_transaction(signed_xdr, skip_memo_required_check=True), timeout=40.0
            )
        except BadRequestError as exc:
            code, message = describe_codes(*result_codes(exc.extras))
            return ClassicResult(tx_hash=tx_hash, successful=False, result_code=code, message=message)
        return ClassicResult(
            tx_hash=str(response.get("hash") or tx_hash),
            successful=bool(response.get("successful", True)),
            ledger=int(response["ledger"]) if response.get("ledger") is not None else None,
        )

    async def transaction(self, tx_hash: str) -> ClassicResult | None:
        try:
            record = await self._call(self._get().transactions().transaction(tx_hash).call())
        except NotFoundError:
            return None
        successful = bool(record.get("successful"))
        return ClassicResult(
            tx_hash=tx_hash,
            successful=successful,
            ledger=int(record["ledger"]) if record.get("ledger") is not None else None,
            result_code=None if successful else "tx_failed",
            message=None if successful else "The transaction failed on the network.",
        )

    async def close(self) -> None:
        if self._server is not None:
            await self._server.close()
        self._server = None


_horizon: HorizonGateway | None = None


def get_horizon() -> HorizonGateway:
    global _horizon
    if _horizon is None:
        _horizon = HorizonClient(get_network())
    return _horizon


def set_horizon(gateway: HorizonGateway | None) -> None:
    """Tests inject a test double here; the application only ever uses HorizonClient."""
    global _horizon
    _horizon = gateway


async def close_horizon() -> None:
    global _horizon
    if isinstance(_horizon, HorizonClient):
        await _horizon.close()
    _horizon = None
