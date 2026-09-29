"""Soroban reads and writes for Stellar Asset Contracts (SACs): whether an asset's SAC exists, its on-chain
metadata, a contract address's balance, and the transaction that deploys a missing SAC.

Every classic asset has exactly one SAC per network, at a contract id derived from the asset itself
(``assets.sac_contract_id``). Anyone may deploy it; BountyFlow's admin action builds that deployment with the
admin's verified wallet as the source account, the wallet signs it, and the backend submits and verifies it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from stellar_sdk import Account, Address, Keypair, TransactionBuilder, scval
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.exceptions import NotFoundError, PrepareTransactionException

from app.blockchain import soroban
from app.blockchain.assets import parse_identifier, sac_contract_id
from app.blockchain.client import get_soroban
from app.blockchain.config import NetworkConfig, get_network
from app.blockchain.transactions import (
    AccountNotFound,
    PreparedCall,
    StellarAdapter,
    TxOutcome,
)
from app.core.money import from_stroops


@dataclass(frozen=True)
class TokenMetadata:
    name: str  # a SAC reports "CODE:ISSUER" (or "native")
    symbol: str
    decimals: int


class TokenGateway(Protocol):
    network: NetworkConfig

    async def contract_exists(self, contract_id: str) -> bool: ...

    async def metadata(self, contract_id: str) -> TokenMetadata: ...

    async def contract_balance(self, identifier: str, holder: str) -> Decimal: ...

    async def prepare_deploy(self, identifier: str, source: str) -> PreparedCall: ...

    async def submit(self, signed_xdr: str, expected_hash: str) -> str: ...

    async def outcome(self, tx_hash: str) -> TxOutcome: ...


def _instance_key(contract_id: str) -> stellar_xdr.LedgerKey:
    return stellar_xdr.LedgerKey(
        type=stellar_xdr.LedgerEntryType.CONTRACT_DATA,
        contract_data=stellar_xdr.LedgerKeyContractData(
            contract=Address(contract_id).to_xdr_sc_address(),
            key=stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_LEDGER_KEY_CONTRACT_INSTANCE),
            durability=stellar_xdr.ContractDataDurability.PERSISTENT,
        ),
    )


def _now() -> datetime:
    return datetime.now(UTC)


class SorobanTokens:
    """Real Soroban RPC implementation. RPC failures surface as ``ChainUnavailable`` (see ``StellarAdapter``)."""

    def __init__(self, network: NetworkConfig) -> None:
        self.network = network
        self._rpc = StellarAdapter(network)  # reuses its timeout / error mapping, submit and outcome polling

    async def contract_exists(self, contract_id: str) -> bool:
        response = await self._rpc._rpc(get_soroban().get_ledger_entries([_instance_key(contract_id)]))
        return bool(response.entries)

    async def _read(self, contract_id: str, function: str, args: list[stellar_xdr.SCVal]) -> Any:
        reader = self.network.arbiter_address or Keypair.random().public_key
        tx = (
            TransactionBuilder(Account(reader, 0), self.network.passphrase, base_fee=self.network.base_fee)
            .append_invoke_contract_function_op(contract_id, function, args)
            .set_timeout(60)
            .build()
        )
        simulation = await self._rpc._rpc(get_soroban().simulate_transaction(tx))
        if simulation.error:
            raise soroban.parse_contract_error(simulation.error)
        if not simulation.results:
            return None
        return scval.to_native(simulation.results[0].xdr)

    async def metadata(self, contract_id: str) -> TokenMetadata:
        name = await self._read(contract_id, "name", [])
        symbol = await self._read(contract_id, "symbol", [])
        decimals = await self._read(contract_id, "decimals", [])
        return TokenMetadata(name=str(name), symbol=str(symbol), decimals=int(decimals))

    async def contract_balance(self, identifier: str, holder: str) -> Decimal:
        contract_id = sac_contract_id(identifier, self.network.passphrase)
        raw = await self._read(contract_id, "balance", [scval.to_address(holder)])
        return from_stroops(int(raw or 0))

    async def prepare_deploy(self, identifier: str, source: str) -> PreparedCall:
        server = get_soroban()
        try:
            account = await self._rpc._rpc(server.load_account(source))
        except NotFoundError as exc:
            raise AccountNotFound(
                "This wallet account does not exist on the network yet. Fund it first "
                "(on Testnet use Friendbot: https://friendbot.stellar.org/?addr=<address>)."
            ) from exc
        tx = (
            TransactionBuilder(account, self.network.passphrase, base_fee=self.network.base_fee)
            .append_create_stellar_asset_contract_from_asset_op(parse_identifier(identifier).to_stellar())
            .set_timeout(self.network.tx_timeout_seconds)
            .build()
        )
        simulation = await self._rpc._rpc(server.simulate_transaction(tx))
        if simulation.error:
            raise soroban.parse_contract_error(simulation.error)
        try:
            prepared = await self._rpc._rpc(server.prepare_transaction(tx, simulation))
        except PrepareTransactionException as exc:
            raise soroban.parse_contract_error(str(exc.simulate_transaction_response.error)) from exc
        return PreparedCall(
            unsigned_xdr=prepared.to_xdr(),
            tx_hash=prepared.hash_hex(),
            fee_stroops=prepared.transaction.fee,
            expires_at=_now() + timedelta(seconds=self.network.tx_timeout_seconds),
        )

    async def submit(self, signed_xdr: str, expected_hash: str) -> str:
        return await self._rpc.submit(signed_xdr, expected_hash)

    async def outcome(self, tx_hash: str) -> TxOutcome:
        return await self._rpc.get_outcome(tx_hash)


_tokens: TokenGateway | None = None


def get_tokens() -> TokenGateway:
    global _tokens
    if _tokens is None:
        _tokens = SorobanTokens(get_network())
    return _tokens


def set_tokens(gateway: TokenGateway | None) -> None:
    """Tests inject a test double here; the application only ever uses SorobanTokens."""
    global _tokens
    _tokens = gateway
