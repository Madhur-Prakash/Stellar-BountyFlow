"""Test double for `app.blockchain.transactions.StellarAdapter` (tests only — never used by the application).

It behaves like Soroban RPC plus the deployed BountyEscrow contract, without a network:

* ``prepare`` builds a **real** Stellar transaction envelope (InvokeHostFunction with the XDR-encoded contract
  arguments, the caller's wallet as source account, a sequence number and time bounds) and returns its XDR and hash.
  Contract errors surface at prepare time, like RPC simulation.
* Tests sign that XDR with a real ``Keypair``; the backend's real ``verify_signed_envelope`` checks the signature.
* ``submit`` decodes the signed envelope, enforces sequence numbers (``txBAD_SEQ``) and executes the call against the
  in-memory contract model (`escrow_model.py`). A contract error becomes a FAILED outcome, like on-chain.
* ``get_outcome`` / ``read_escrow`` / ``read_assignment`` answer from that state.

Hooks let tests inject failures and races:

* ``rpc_down``: every call raises ChainUnavailable (the RPC is unreachable).
* ``outcomes_down``: only ``get_outcome`` raises ChainUnavailable (the RPC accepted a submission, then fails while the
  backend polls for its result).
* ``report_pending``: ``get_outcome`` answers PENDING (known to the network, not settled yet).
* ``lose_next_submit_response``: the next submission is applied, then its response is lost (ChainUnavailable).
* ``reject_duplicates``: re-sending an already-applied transaction is rejected with ``txBAD_SEQ`` (its sequence number
  is consumed), as on the real network. By default the re-send answers DUPLICATE, like a transaction still in the
  RPC's pending queue.
* ``fail_next_execution``: the next submitted call fails on-chain with that contract error code.
* ``on_submit`` / ``on_outcome``: one-shot async callbacks run inside ``submit`` (after the network accepted the
  transaction) / ``get_outcome`` (before answering), e.g. to race a concurrent database write against the request.
* ``submit_latency``: seconds every ``submit`` waits before answering (widens race windows).
* ``advance_time`` / ``freeze_clock``: move or stop the chain clock (contract ``now`` and transaction time bounds).

``submit_calls`` counts every call to ``submit`` (including duplicates and rejections); ``submitted`` lists the hashes
of the transactions the network actually applied.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from stellar_sdk import (
    Account,
    Address,
    FeeBumpTransactionEnvelope,
    InvokeHostFunction,
    Keypair,
    StrKey,
    TransactionBuilder,
    TransactionEnvelope,
)
from stellar_sdk import xdr as stellar_xdr

from app.blockchain.config import NetworkConfig
from app.blockchain.soroban import CONTRACT_ERRORS, ContractCall, ContractError, EscrowSnapshot
from app.blockchain.transactions import ChainRejected, ChainUnavailable, PreparedCall, RelayedCall, TxOutcome
from tests.support.escrow_model import Ledger, execute, view

# Stands in for the smart wallet's own `__check_auth` (a WebAuthn signature check the fake cannot run): a
# signature scval equal to this marks an authorization the "wallet" rejects.
REJECTED_WALLET_SIGNATURE = stellar_xdr.SCVal(
    stellar_xdr.SCValType.SCV_SYMBOL, sym=stellar_xdr.SCSymbol(b"bad")
)


class FakeStellarChain:
    def __init__(self, network: NetworkConfig) -> None:
        self.network = network
        self.storage: dict[str, dict[str, Any]] = {}
        # hash -> (call, caller, sequence, sequence account); the sequence account is the envelope source (the
        # sponsor for relayed smart-wallet transactions, the caller otherwise). A None call deploys a wallet.
        self.pending: dict[str, tuple[ContractCall | None, str, int, str]] = {}
        # Smart-wallet invocations prepared with the sponsor as source: host function XDR -> (call, wallet).
        self.relayable: dict[bytes, tuple[ContractCall, str]] = {}
        self.fee_bumps: dict[str, str] = {}  # inner hash -> fee source of the bump that carried it
        self.contracts: dict[str, str] = {}  # deployed wallet contract id -> wasm hash
        self.deploys: dict[str, tuple[str, str]] = {}  # relayed hash -> (contract id, wasm hash)
        self.sponsor_balance = 10_000 * 10_000_000
        self.relay_calls = 0
        self.outcomes: dict[str, TxOutcome] = {}
        self.sequences: defaultdict[str, int] = defaultdict(lambda: 4_200_000_000)
        self.ledger = 5_000_000
        self.clock_offset = 0
        self.frozen_at: int | None = None
        self.rpc_down = False
        self.outcomes_down = False
        self.report_pending = False
        self.lose_next_submit_response = False
        self.reject_duplicates = False
        self.fail_next_execution: int | None = None
        self.on_submit: Callable[[], Awaitable[None]] | None = None
        self.on_outcome: Callable[[], Awaitable[None]] | None = None
        self.submit_latency = 0.0
        self.submit_calls = 0
        self.submitted: list[str] = []

    # --- helpers -----------------------------------------------------------------------------------

    def now(self) -> int:
        base = self.frozen_at if self.frozen_at is not None else int(time.time())
        return base + self.clock_offset

    def advance_time(self, seconds: int) -> None:
        self.clock_offset += seconds

    def freeze_clock(self) -> None:
        """Stops the chain clock (contract ``now`` and transaction time bounds), so identical prepares build
        byte-identical transactions no matter how long the test takes between them."""
        self.frozen_at = int(time.time())

    def _check_rpc(self) -> None:
        if self.rpc_down:
            raise ChainUnavailable("The Stellar RPC timed out. Please try again.")

    def _run(self, call: ContractCall, source: str, *, commit: bool) -> dict[str, Any]:
        rows = copy.deepcopy(self.storage)
        result = execute(Ledger(rows), call, source, self.now())
        if commit:
            self.storage = rows
        return result

    # --- ChainAdapter interface ----------------------------------------------------------------------

    async def prepare(self, call: ContractCall, source: str) -> PreparedCall:
        self._check_rpc()
        self._run(call, source, commit=False)  # "simulation": contract errors surface before signing
        if StrKey.is_valid_contract(source):
            return self._prepare_for_contract_account(call, source)
        sequence = self.sequences[source]
        tx = (
            TransactionBuilder(
                Account(source, sequence), self.network.passphrase, base_fee=self.network.base_fee
            )
            .append_invoke_contract_function_op(self.network.contract_id or "", call.function, call.args)
            # What set_timeout() does, on the chain's clock: identical inputs within one second (e.g. a double click)
            # build a byte-identical transaction, exactly as on the real network.
            .add_time_bounds(0, self.now() + self.network.tx_timeout_seconds)
            .build()
        )
        tx_hash = tx.hash_hex()
        self.pending[tx_hash] = (call, source, sequence + 1, source)
        return PreparedCall(
            unsigned_xdr=tx.to_xdr(),
            tx_hash=tx_hash,
            fee_stroops=tx.transaction.fee,
            expires_at=datetime.now(UTC) + timedelta(seconds=self.network.tx_timeout_seconds),
        )

    async def submit(self, signed_xdr: str, expected_hash: str) -> str:
        self.submit_calls += 1
        self._check_rpc()
        if self.submit_latency:
            await asyncio.sleep(self.submit_latency)
        fee_source: str | None = None
        if FeeBumpTransactionEnvelope.is_fee_bump_transaction_envelope(signed_xdr):
            # A sponsor fee bump: the network applies (and reports) the inner transaction, charged to the sponsor.
            bump = FeeBumpTransactionEnvelope.from_xdr(signed_xdr, self.network.passphrase)
            if not bump.signatures:
                raise ChainRejected("The transaction signature is invalid or missing.", "txBAD_AUTH")
            fee_source = bump.transaction.fee_source.account_id
            envelope = bump.transaction.inner_transaction_envelope
        else:
            envelope = TransactionEnvelope.from_xdr(signed_xdr, self.network.passphrase)
        tx_hash = envelope.hash_hex()
        if tx_hash in self.outcomes:
            if self.reject_duplicates:
                raise ChainRejected("Sequence number conflict. Please retry.", "txBAD_SEQ")
            return tx_hash  # DUPLICATE
        if tx_hash not in self.pending:
            raise ChainRejected("The transaction is malformed.", "txMALFORMED")
        call, source, sequence, seq_account = self.pending[tx_hash]
        if self.sequences[seq_account] + 1 != sequence:
            raise ChainRejected("Sequence number conflict. Please retry.", "txBAD_SEQ")
        del self.pending[tx_hash]
        self.sequences[seq_account] = sequence
        self.ledger += 1
        self.submitted.append(tx_hash)
        if fee_source is not None:
            self.fee_bumps[tx_hash] = fee_source
        if call is None:  # a relayed passkey wallet deployment
            contract_id, wasm = self.deploys[tx_hash]
            self.contracts[contract_id] = wasm
            self.outcomes[tx_hash] = TxOutcome(
                status="SUCCESS", ledger=self.ledger, ledger_close_time=datetime.now(UTC), fee_charged=150_000
            )
            return tx_hash
        if self.fail_next_execution is not None:
            code, self.fail_next_execution = self.fail_next_execution, None
            self.outcomes[tx_hash] = TxOutcome(
                status="FAILED",
                ledger=self.ledger,
                result_code="txFAILED",
                failure_reason=CONTRACT_ERRORS.get(code, ("", "The transaction failed."))[1],
            )
        else:
            try:
                result = self._run(call, source, commit=True)
                self.outcomes[tx_hash] = TxOutcome(
                    status="SUCCESS",
                    ledger=self.ledger,
                    ledger_close_time=datetime.now(UTC),
                    return_value=result,
                    fee_charged=120_000,
                )
            except ContractError as exc:
                self.outcomes[tx_hash] = TxOutcome(
                    status="FAILED", ledger=self.ledger, result_code="txFAILED", failure_reason=exc.message
                )
        if self.on_submit is not None:
            hook, self.on_submit = self.on_submit, None
            await hook()
        if self.lose_next_submit_response:
            self.lose_next_submit_response = False
            raise ChainUnavailable("The Stellar RPC timed out. Please try again.")
        return tx_hash

    async def get_outcome(self, tx_hash: str) -> TxOutcome:
        self._check_rpc()
        if self.outcomes_down:
            raise ChainUnavailable("The Stellar RPC timed out. Please try again.")
        if self.report_pending:
            return TxOutcome(status="PENDING")
        if self.on_outcome is not None:
            hook, self.on_outcome = self.on_outcome, None
            await hook()
        return self.outcomes.get(tx_hash, TxOutcome(status="NOT_FOUND"))

    async def read_escrow(self, bid: bytes, contract_id: str | None = None) -> EscrowSnapshot | None:
        # Escrow ids are random per bounty, so one store serves every deployment (contract_id is not needed).
        self._check_rpc()
        value = self.storage.get(f"escrow:{bid.hex()}")
        if value is None:
            return None
        fields = {k: value[k] for k in EscrowSnapshot.__dataclass_fields__ if k in value}
        if "arbiters" in fields:
            fields["arbiters"] = tuple(fields["arbiters"])
        if "milestones" in fields:
            fields["milestones"] = tuple((m["amount"], m["paid"]) for m in fields["milestones"])
        return EscrowSnapshot(**fields)

    async def read_assignment(
        self, bid: bytes, contributor: str, contract_id: str | None = None
    ) -> str | None:
        self._check_rpc()
        value = self.storage.get(f"assign:{bid.hex()}:{contributor}")
        return None if value is None else str(value.get("state"))

    async def read(self, call: ContractCall) -> Any:
        """Read-only contract views (escrow v2), answered in the contract's native shapes."""
        self._check_rpc()
        return view(Ledger(self.storage), call)

    # --- smart wallets and sponsorship --------------------------------------------------------------

    def _sponsor(self) -> Keypair:
        from app.blockchain.sponsorship import sponsor_keypair

        sponsor = sponsor_keypair()
        if sponsor is None:
            raise ChainUnavailable("Smart-wallet transactions need the platform fee sponsor.")
        return sponsor

    def _prepare_for_contract_account(self, call: ContractCall, wallet: str) -> PreparedCall:
        """Like the real adapter: the sponsor sources the envelope, the wallet gets an unsigned, address-bound
        authorization entry for the call."""
        sponsor = self._sponsor()
        invocation = stellar_xdr.InvokeContractArgs(
            contract_address=Address(self.network.contract_id or "").to_xdr_sc_address(),
            function_name=stellar_xdr.SCSymbol(call.function.encode()),
            args=call.args,
        )
        entry = stellar_xdr.SorobanAuthorizationEntry(
            credentials=stellar_xdr.SorobanCredentials(
                type=stellar_xdr.SorobanCredentialsType.SOROBAN_CREDENTIALS_ADDRESS_V2,
                address_v2=stellar_xdr.SorobanAddressCredentials(
                    address=Address(wallet).to_xdr_sc_address(),
                    nonce=stellar_xdr.Int64(len(self.relayable) + 1),
                    signature_expiration_ledger=stellar_xdr.Uint32(self.ledger + 70),
                    signature=stellar_xdr.SCVal(stellar_xdr.SCValType.SCV_VOID),
                ),
            ),
            root_invocation=stellar_xdr.SorobanAuthorizedInvocation(
                function=stellar_xdr.SorobanAuthorizedFunction(
                    type=stellar_xdr.SorobanAuthorizedFunctionType.SOROBAN_AUTHORIZED_FUNCTION_TYPE_CONTRACT_FN,
                    contract_fn=invocation,
                ),
                sub_invocations=[],
            ),
        )
        sequence = self.sequences[sponsor.public_key]
        tx = (
            TransactionBuilder(
                Account(sponsor.public_key, sequence), self.network.passphrase, base_fee=self.network.base_fee
            )
            .append_invoke_contract_function_op(
                self.network.contract_id or "", call.function, call.args, auth=[entry]
            )
            .add_time_bounds(0, self.now() + self.network.tx_timeout_seconds)
            .build()
        )
        op = tx.transaction.operations[0]
        assert isinstance(op, InvokeHostFunction)
        self.relayable[op.host_function.to_xdr_bytes()] = (call, wallet)
        return PreparedCall(
            unsigned_xdr=tx.to_xdr(),
            tx_hash=tx.hash_hex(),
            fee_stroops=tx.transaction.fee,
            expires_at=datetime.now(UTC) + timedelta(seconds=self.network.tx_timeout_seconds),
        )

    async def relay(
        self,
        host_function: stellar_xdr.HostFunction,
        auth: list[stellar_xdr.SorobanAuthorizationEntry],
        sponsor: Keypair,
        max_fee: int,
    ) -> RelayedCall:
        self._check_rpc()
        self.relay_calls += 1
        call: ContractCall | None = None
        wallet = sponsor.public_key
        deploy: tuple[str, str] | None = None
        if host_function.type == stellar_xdr.HostFunctionType.HOST_FUNCTION_TYPE_CREATE_CONTRACT_V2:
            from app.blockchain.passkey import _contract_id

            create = host_function.create_contract_v2
            assert create is not None and create.executable.wasm_hash is not None
            deploy = (_contract_id(create.contract_id_preimage), create.executable.wasm_hash.hash.hex())
        else:
            known = self.relayable.get(host_function.to_xdr_bytes())
            if known is None:
                raise ContractError(
                    None, "The contract rejected this transaction during simulation.", "unknown"
                )
            call, wallet = known
            for entry in auth:
                credentials = entry.credentials.address_v2 or entry.credentials.address
                if credentials is not None and credentials.signature == REJECTED_WALLET_SIGNATURE:
                    raise ContractError(
                        None, "HostError: Error(Auth, InvalidAction)", "Error(Auth, InvalidAction)"
                    )
            self._run(call, wallet, commit=False)
        fee = 350_000
        if fee > max_fee:
            raise ContractError(None, f"The network fee ({fee} stroops) is above the sponsorship limit.")
        sequence = self.sequences[sponsor.public_key]
        tx = (
            TransactionBuilder(
                Account(sponsor.public_key, sequence), self.network.passphrase, base_fee=self.network.base_fee
            )
            .append_operation(InvokeHostFunction(host_function=host_function, auth=auth))
            .add_time_bounds(0, self.now() + self.network.tx_timeout_seconds)
            .build()
        )
        tx.sign(sponsor)
        tx_hash = tx.hash_hex()
        self.pending[tx_hash] = (call, wallet, sequence + 1, sponsor.public_key)
        if deploy is not None:
            self.deploys[tx_hash] = deploy
        return RelayedCall(signed_xdr=tx.to_xdr(), tx_hash=tx_hash, fee_stroops=fee, sequence=sequence + 1)

    async def native_balance(self, address: str) -> int | None:
        self._check_rpc()
        return self.sponsor_balance

    async def contract_wasm_hash(self, contract_id: str) -> str | None:
        self._check_rpc()
        return self.contracts.get(contract_id)

    async def latest_ledger(self) -> int:
        self._check_rpc()
        return self.ledger

    # --- direct manipulation (for tests that model out-of-band chain activity) ----------------------

    def invoke_directly(self, call: ContractCall, source: str) -> dict[str, Any]:
        """Execute a contract call as if signed and submitted outside BountyFlow."""
        return self._run(call, source, commit=True)
