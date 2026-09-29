"""Test double for `app.blockchain.horizon.HorizonClient` and `app.blockchain.tokens.SorobanTokens` (tests only).

It models accounts (balances and trustlines), classic ``changeTrust`` submissions, and Stellar Asset Contracts:

* ``accounts``: explicitly configured accounts (``add_account``). Any other G-address is *permissive* by default: it
  exists with plenty of XLM and a trustline for every asset in ``known_assets``, so tests that are not about assets
  behave exactly as before. Set ``permissive = False`` to make unknown accounts missing.
* ``submit`` decodes a **real** signed envelope and applies its ``changeTrust`` operations to the source account.
  ``reject_next_submit`` makes the next one fail with that Horizon result code.
* ``contracts``: deployed SAC ids (every ``known_assets`` SAC plus the native one). ``prepare_deploy`` builds a real
  transaction envelope; ``submit`` / ``outcome`` for it deploy the contract.
* ``horizon_down`` / ``rpc_down`` raise the transient errors the real clients raise.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from stellar_sdk import (
    Account,
    Asset,
    ChangeTrust,
    FeeBumpTransactionEnvelope,
    TransactionBuilder,
    TransactionEnvelope,
)

from app.blockchain.assets import NATIVE, parse_identifier, sac_contract_id
from app.blockchain.config import NetworkConfig
from app.blockchain.horizon import AccountState, AssetBalance, ClassicResult, HorizonUnavailable
from app.blockchain.tokens import TokenMetadata
from app.blockchain.transactions import ChainUnavailable, PreparedCall, TxOutcome

TESTNET_USDC = "USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
PLENTY = Decimal("1000000")


class FakeLedger:
    def __init__(self, network: NetworkConfig) -> None:
        self.network = network
        self.accounts: dict[str, AccountState] = {}
        self.known_assets: set[str] = {TESTNET_USDC}
        self.permissive = True
        self.contracts: set[str] = {sac_contract_id(NATIVE, network.passphrase)} | {
            sac_contract_id(a, network.passphrase) for a in self.known_assets
        }
        self.contract_balances: dict[tuple[str, str], Decimal] = {}
        self.issuer_flags: dict[str, dict[str, bool]] = {}
        self.classic: dict[str, ClassicResult] = {}
        self.deploys: dict[str, str] = {}  # pending deploy hash -> identifier
        self.outcomes: dict[str, TxOutcome] = {}
        self.horizon_down = False
        self.rpc_down = False
        self.reject_next_submit: str | None = None
        self.ledger = 7_000_000
        self.sequences: dict[str, int] = {}

    # --- setup ----------------------------------------------------------------------------------

    def add_asset(self, identifier: str, *, deployed: bool = True) -> None:
        self.known_assets.add(identifier)
        if deployed:
            self.contracts.add(sac_contract_id(identifier, self.network.passphrase))

    def add_account(
        self, address: str, *, xlm: str = "100", assets: dict[str, str] | None = None, authorized: bool = True
    ) -> None:
        balances = {NATIVE: AssetBalance(NATIVE, Decimal(xlm))}
        for identifier, amount in (assets or {}).items():
            balances[identifier] = AssetBalance(
                identifier, Decimal(amount), limit=Decimal("922337203685.4775807"), is_authorized=authorized
            )
        self.accounts[address] = AccountState(
            address=address,
            sequence=self.sequences.get(address, 4_100_000_000),
            balances=balances,
            subentry_count=len(balances) - 1,
            flags=self.issuer_flags.get(address, {}),
        )

    def remove_account(self, address: str) -> None:
        self.accounts.pop(address, None)

    # --- Horizon ----------------------------------------------------------------------------------

    def _horizon(self) -> None:
        if self.horizon_down:
            raise HorizonUnavailable("Horizon timed out. Please try again.")

    async def load_account(self, address: str) -> AccountState | None:
        self._horizon()
        if address in self.accounts:
            return self.accounts[address]
        issuers = {parse_identifier(a).issuer for a in self.known_assets}
        if address in issuers:
            return AccountState(
                address, 1, {NATIVE: AssetBalance(NATIVE, PLENTY)}, flags=self.issuer_flags.get(address, {})
            )
        if not self.permissive:
            return None
        balances = {NATIVE: AssetBalance(NATIVE, PLENTY)}
        for identifier in self.known_assets:
            balances[identifier] = AssetBalance(identifier, PLENTY, limit=PLENTY * 10)
        return AccountState(address, 1, balances, subentry_count=len(self.known_assets))

    def _unwrap(self, signed_xdr: str) -> tuple[TransactionEnvelope, str | None]:
        """A fee-bumped envelope applies its inner transaction, exactly as the network does. Returns the inner
        envelope and the fee bump's own hash (None when it is not a fee bump)."""
        if FeeBumpTransactionEnvelope.is_fee_bump_transaction_envelope(signed_xdr):
            bump = FeeBumpTransactionEnvelope.from_xdr(signed_xdr, self.network.passphrase)
            return bump.transaction.inner_transaction_envelope, bump.hash_hex()
        return TransactionEnvelope.from_xdr(signed_xdr, self.network.passphrase), None

    async def submit(self, signed_xdr: str) -> ClassicResult:
        self._horizon()
        envelope, bump_hash = self._unwrap(signed_xdr)
        tx_hash = envelope.hash_hex()
        if tx_hash in self.classic:
            return self.classic[tx_hash]
        self.ledger += 1
        if self.reject_next_submit:
            code, self.reject_next_submit = self.reject_next_submit, None
            result = ClassicResult(
                tx_hash=tx_hash, successful=False, result_code=code, message=f"failed ({code})"
            )
            self._remember(result, bump_hash)
            return result
        source = envelope.transaction.source.account_id
        account = await self.load_account(source)
        if account is None:
            result = ClassicResult(tx_hash, False, result_code="tx_no_source_account", message="No account")
            self._remember(result, bump_hash)
            return result
        balances = dict(account.balances)
        for op in envelope.transaction.operations:
            if isinstance(op, ChangeTrust) and isinstance(op.asset, Asset):
                identifier = f"{op.asset.code}:{op.asset.issuer}"
                if Decimal(op.limit) == 0:
                    balances.pop(identifier, None)
                else:
                    balances.setdefault(
                        identifier, AssetBalance(identifier, Decimal(0), limit=Decimal(op.limit))
                    )
        self.accounts[source] = replace(
            account, sequence=account.sequence + 1, balances=balances, subentry_count=len(balances) - 1
        )
        result = ClassicResult(tx_hash=tx_hash, successful=True, ledger=self.ledger)
        self._remember(result, bump_hash)
        return result

    def _remember(self, result: ClassicResult, bump_hash: str | None) -> None:
        """Horizon answers for a fee-bumped transaction under both its own and its inner hash."""
        self.classic[result.tx_hash] = result
        if bump_hash:
            self.classic[bump_hash] = result

    async def transaction(self, tx_hash: str) -> ClassicResult | None:
        self._horizon()
        return self.classic.get(tx_hash)

    # --- Soroban tokens -------------------------------------------------------------------------

    def _rpc(self) -> None:
        if self.rpc_down:
            raise ChainUnavailable("The Stellar RPC timed out. Please try again.")

    async def contract_exists(self, contract_id: str) -> bool:
        self._rpc()
        return contract_id in self.contracts

    async def metadata(self, contract_id: str) -> TokenMetadata:
        self._rpc()
        for identifier in [NATIVE, *self.known_assets]:
            if (
                sac_contract_id(identifier, self.network.passphrase) == contract_id
                and contract_id in self.contracts
            ):
                ref = parse_identifier(identifier)
                return TokenMetadata(
                    name=ref.identifier, symbol=ref.code if not ref.is_native else "native", decimals=7
                )
        from app.blockchain.soroban import ContractError

        raise ContractError(None, "The contract rejected this transaction during simulation.")

    async def contract_balance(self, identifier: str, holder: str) -> Decimal:
        self._rpc()
        return self.contract_balances.get((identifier, holder), PLENTY if self.permissive else Decimal(0))

    async def prepare_deploy(self, identifier: str, source: str) -> PreparedCall:
        self._rpc()
        tx = (
            TransactionBuilder(
                Account(source, self.sequences.get(source, 4_100_000_000)), self.network.passphrase
            )
            .append_create_stellar_asset_contract_from_asset_op(parse_identifier(identifier).to_stellar())
            .set_timeout(self.network.tx_timeout_seconds)
            .build()
        )
        self.deploys[tx.hash_hex()] = identifier
        return PreparedCall(
            unsigned_xdr=tx.to_xdr(),
            tx_hash=tx.hash_hex(),
            fee_stroops=tx.transaction.fee,
            expires_at=datetime.now(UTC) + timedelta(seconds=self.network.tx_timeout_seconds),
        )

    async def submit_soroban(self, signed_xdr: str, expected_hash: str) -> str:
        self._rpc()
        tx_hash = TransactionEnvelope.from_xdr(signed_xdr, self.network.passphrase).hash_hex()
        identifier = self.deploys.pop(tx_hash, None)
        if identifier is not None:
            self.ledger += 1
            self.add_asset(identifier)
            self.outcomes[tx_hash] = TxOutcome(
                status="SUCCESS", ledger=self.ledger, ledger_close_time=datetime.now(UTC)
            )
        return tx_hash

    async def outcome(self, tx_hash: str) -> TxOutcome:
        self._rpc()
        return self.outcomes.get(tx_hash, TxOutcome(status="NOT_FOUND"))


class FakeTokens:
    """Adapter exposing FakeLedger's token half under the TokenGateway method names."""

    def __init__(self, ledger: FakeLedger) -> None:
        self.ledger = ledger
        self.network = ledger.network

    async def contract_exists(self, contract_id: str) -> bool:
        return await self.ledger.contract_exists(contract_id)

    async def metadata(self, contract_id: str) -> TokenMetadata:
        return await self.ledger.metadata(contract_id)

    async def contract_balance(self, identifier: str, holder: str) -> Decimal:
        return await self.ledger.contract_balance(identifier, holder)

    async def prepare_deploy(self, identifier: str, source: str) -> PreparedCall:
        return await self.ledger.prepare_deploy(identifier, source)

    async def submit(self, signed_xdr: str, expected_hash: str) -> str:
        return await self.ledger.submit_soroban(signed_xdr, expected_hash)

    async def outcome(self, tx_hash: str) -> TxOutcome:
        return await self.ledger.outcome(tx_hash)
