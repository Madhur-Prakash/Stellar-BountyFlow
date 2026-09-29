"""Test double for the attestation registry adapter (tests only; the application uses StellarAttestationChain).

It models contracts/attestations/src/lib.rs in memory: sequential ids, one attestation per (bounty, contributor,
payout), ``AlreadyAttested`` / ``AlreadyRevoked`` / ``NotFound`` errors, revocation with a reason. Submissions
build and "sign" nothing; each call returns a fresh transaction hash whose outcome ``get_outcome`` reports.

Hooks:

* ``rpc_down``: every call raises ChainUnavailable.
* ``lose_next_response``: the next attest/revoke is applied on-chain, then its response is lost (ChainUnavailable).
* ``fail_next``: the next attest/revoke is included but fails (no state change).
* ``pending``: outcomes are reported as PENDING until cleared.
* ``drop_next``: the next transaction is never included (NOT_FOUND forever).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import UTC, datetime

from app.blockchain.transactions import ChainUnavailable, TxOutcome
from app.modules.reputation.chain import (
    AttestationConfig,
    AttestationError,
    Completion,
    OnchainAttestation,
    parse_error,
)


def _err(code: int) -> AttestationError:
    return parse_error(f"HostError: Error(Contract, #{code})")


class FakeAttestationChain:
    def __init__(self, config: AttestationConfig) -> None:
        self.config = config
        self.records: dict[int, OnchainAttestation] = {}
        self.outcomes: dict[str, TxOutcome] = {}
        self.ledger = 7_000_000
        self.submitted: list[str] = []
        self.rpc_down = False
        self.lose_next_response = False
        self.fail_next = False
        self.pending = False
        self.drop_next = False

    def _check(self) -> None:
        if self.rpc_down:
            raise ChainUnavailable("The Stellar RPC timed out. Please try again.")

    def _hash(self, label: str) -> str:
        return hashlib.sha256(f"{label}:{len(self.submitted)}:{time.time_ns()}".encode()).hexdigest()

    def _key(self, bounty_id: str, contributor: str, payout_tx: str) -> int | None:
        for record in self.records.values():
            if (record.bounty_id, record.contributor, record.payout_tx) == (
                bounty_id,
                contributor,
                payout_tx,
            ):
                return record.id
        return None

    def _send(self, label: str, apply: object) -> str:
        tx_hash = self._hash(label)
        self.submitted.append(tx_hash)
        if self.drop_next:
            self.drop_next = False
            return tx_hash
        self.ledger += 1
        if self.fail_next:
            self.fail_next = False
            self.outcomes[tx_hash] = TxOutcome(
                status="FAILED",
                ledger=self.ledger,
                result_code="txFAILED",
                failure_reason="The transaction failed.",
            )
        else:
            apply()  # type: ignore[operator]
            self.outcomes[tx_hash] = TxOutcome(
                status="SUCCESS", ledger=self.ledger, ledger_close_time=datetime.now(UTC)
            )
        if self.lose_next_response:
            self.lose_next_response = False
            raise ChainUnavailable("The Stellar RPC timed out. Please try again.")
        return tx_hash

    # --- AttestationChain interface --------------------------------------------------------------

    async def attest(self, completion: Completion) -> str:
        self._check()
        attester = self.config.attester_address or ""
        # Simulation: contract errors surface before anything is sent.
        if self._key(completion.bounty_id.hex(), completion.contributor, completion.payout_tx.hex()):
            raise _err(2)
        if completion.contributor == attester:
            raise _err(8)
        if completion.amount <= 0:
            raise _err(4)
        if completion.completed_at <= 0 or completion.completed_at > int(time.time()):
            raise _err(5)

        def apply() -> None:
            new_id = len(self.records) + 1
            index = sum(1 for r in self.records.values() if r.contributor == completion.contributor)
            self.records[new_id] = OnchainAttestation(
                id=new_id,
                attester=attester,
                contributor=completion.contributor,
                bounty_id=completion.bounty_id.hex(),
                escrow_contract=completion.escrow_contract,
                payout_tx=completion.payout_tx.hex(),
                token=completion.token,
                amount=completion.amount,
                completed_at=completion.completed_at,
                attested_at=int(time.time()),
                contributor_index=index,
                revoked=False,
                revoked_at=0,
                revocation_reason="",
            )

        return self._send("attest", apply)

    async def revoke(self, onchain_id: int, reason: str) -> str:
        self._check()
        record = self.records.get(onchain_id)
        if record is None:
            raise _err(1)
        if record.revoked:
            raise _err(6)
        if not reason or len(reason.encode()) > 200:
            raise _err(7)

        def apply() -> None:
            self.records[onchain_id] = replace(
                record, revoked=True, revoked_at=int(time.time()), revocation_reason=reason
            )

        return self._send("revoke", apply)

    async def get_outcome(self, tx_hash: str) -> TxOutcome:
        self._check()
        if self.pending:
            return TxOutcome(status="PENDING")
        return self.outcomes.get(tx_hash, TxOutcome(status="NOT_FOUND"))

    async def wait_for_outcome(self, tx_hash: str, timeout: float = 45.0) -> TxOutcome:
        return await self.get_outcome(tx_hash)

    async def get(self, onchain_id: int) -> OnchainAttestation | None:
        self._check()
        return self.records.get(onchain_id)

    async def find(self, bounty_id: bytes, contributor: str, payout_tx: bytes) -> OnchainAttestation | None:
        self._check()
        found = self._key(bounty_id.hex(), contributor, payout_tx.hex())
        return self.records.get(found) if found else None

    async def count_by_contributor(self, contributor: str) -> int:
        self._check()
        return sum(1 for r in self.records.values() if r.contributor == contributor)

    # --- out-of-band activity ------------------------------------------------------------------

    def tamper(self, onchain_id: int, **changes: object) -> None:
        """Overwrite a record's fields (models drift between the database and the chain)."""
        self.records[onchain_id] = replace(self.records[onchain_id], **changes)  # type: ignore[arg-type]
