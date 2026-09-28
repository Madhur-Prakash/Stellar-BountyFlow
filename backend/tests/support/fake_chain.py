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

from stellar_sdk import Account, TransactionBuilder, TransactionEnvelope

from app.blockchain.config import NetworkConfig
from app.blockchain.soroban import CONTRACT_ERRORS, ContractCall, ContractError, EscrowSnapshot
from app.blockchain.transactions import ChainRejected, ChainUnavailable, PreparedCall, TxOutcome
from tests.support.escrow_model import Ledger, execute


class FakeStellarChain:
    def __init__(self, network: NetworkConfig) -> None:
        self.network = network
        self.storage: dict[str, dict[str, Any]] = {}
        self.pending: dict[str, tuple[ContractCall, str, int]] = {}  # hash -> (call, source, sequence)
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
        self.pending[tx_hash] = (call, source, sequence + 1)
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
        envelope = TransactionEnvelope.from_xdr(signed_xdr, self.network.passphrase)
        tx_hash = envelope.hash_hex()
        if tx_hash in self.outcomes:
            if self.reject_duplicates:
                raise ChainRejected("Sequence number conflict. Please retry.", "txBAD_SEQ")
            return tx_hash  # DUPLICATE
        if tx_hash not in self.pending:
            raise ChainRejected("The transaction is malformed.", "txMALFORMED")
        call, source, sequence = self.pending[tx_hash]
        if self.sequences[source] + 1 != sequence:
            raise ChainRejected("Sequence number conflict. Please retry.", "txBAD_SEQ")
        del self.pending[tx_hash]
        self.sequences[source] = sequence
        self.ledger += 1
        self.submitted.append(tx_hash)
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

    async def read_escrow(self, bid: bytes) -> EscrowSnapshot | None:
        self._check_rpc()
        value = self.storage.get(f"escrow:{bid.hex()}")
        if value is None:
            return None
        return EscrowSnapshot(**{k: value[k] for k in EscrowSnapshot.__dataclass_fields__ if k in value})

    async def read_assignment(self, bid: bytes, contributor: str) -> str | None:
        self._check_rpc()
        value = self.storage.get(f"assign:{bid.hex()}:{contributor}")
        return None if value is None else str(value.get("state"))

    # --- direct manipulation (for tests that model out-of-band chain activity) ----------------------

    def invoke_directly(self, call: ContractCall, source: str) -> dict[str, Any]:
        """Execute a contract call as if signed and submitted outside BountyFlow."""
        return self._run(call, source, commit=True)
