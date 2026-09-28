"""Fidelity of the test escrow model (tests/support/escrow_model.py, executed by the `FakeStellarChain` test double)
against the Soroban contract (contracts/bounty_escrow/src/lib.rs): every public function, its state transitions, and
every error code in the order the contract checks them. Scenarios mirror contracts/bounty_escrow/src/test.rs."""

from __future__ import annotations

from typing import Any

import pytest

from app.blockchain import soroban
from app.blockchain.soroban import ContractCall, ContractError
from tests.support.escrow_model import Ledger, execute

NOW = 1_800_000_000
DEADLINE = NOW + 30 * 86400
REQ = "G-REQUESTER"
ARB = "G-ARBITER"
ALICE = "G-ALICE"
BOB = "G-BOB"
CAROL = "G-CAROL"
TOKEN = "C-NATIVE"
BID = bytes(range(32))
I128_MAX = 2**127 - 1


class Chain:
    def __init__(self) -> None:
        self.ledger = Ledger({})
        self.now = NOW

    def call(self, call: ContractCall, source: str | None = None) -> dict[str, Any]:
        return execute(self.ledger, call, source or call.auth_address or "", self.now)

    def error(self, call: ContractCall, source: str | None = None) -> str:
        with pytest.raises(ContractError) as info:
            self.call(call, source)
        return info.value.name

    def escrow(self) -> dict[str, Any]:
        value = self.ledger.get(f"escrow:{BID.hex()}")
        assert value is not None
        return value

    def assignment(self, who: str) -> str | None:
        value = self.ledger.get(f"assign:{BID.hex()}:{who}")
        return None if value is None else value["state"]

    def balance(self, who: str) -> int:
        return int((self.ledger.get(f"balance:{who}") or {}).get("stroops", 0))


def create(reward: int = 100, positions: int = 1, deposit: int | None = None, **kw: Any) -> ContractCall:
    return soroban.create_escrow(
        kw.get("requester", REQ),
        kw.get("bid", BID),
        TOKEN,
        reward,
        positions,
        kw.get("arbiter", ARB),
        kw.get("deadline", DEADLINE),
        reward * positions if deposit is None else deposit,
    )


def funded(reward: int = 100, positions: int = 1) -> Chain:
    chain = Chain()
    chain.call(create(reward, positions))
    return chain


def test_create_without_and_with_partial_deposit() -> None:
    chain = Chain()
    e = chain.call(create(100, 2, deposit=0))
    assert e["status"] == "AwaitingFunding" and e["required_amount"] == 200 and e["funded_amount"] == 0
    other = Chain()
    assert other.call(create(100, 2, deposit=150))["status"] == "AwaitingFunding"
    full = Chain()
    e = full.call(create(100, 2, deposit=200))
    assert e["status"] == "Funded" and e["pre_dispute_status"] == "Funded"


def test_create_invalid_params_in_contract_order() -> None:
    chain = funded()
    assert chain.error(create()) == "AlreadyExists"
    fresh = Chain()
    assert fresh.error(create(0)) == "InvalidAmount"
    assert fresh.error(create(-1, deposit=0)) == "InvalidAmount"
    assert fresh.error(create(100, 0, deposit=0)) == "InvalidPositions"
    assert fresh.error(create(100, 101, deposit=0)) == "InvalidPositions"
    assert fresh.error(create(arbiter=REQ)) == "InvalidArbiter"
    assert fresh.error(create(deadline=NOW)) == "DeadlineInPast"
    assert fresh.error(create(I128_MAX, 2, deposit=0)) == "Overflow"
    assert fresh.error(create(100, deposit=-1)) == "InvalidAmount"
    assert fresh.error(create(100, deposit=101)) == "Overfunded"
    # Order: an invalid arbiter is reported before a past deadline, as in the contract.
    assert fresh.error(create(arbiter=REQ, deadline=NOW)) == "InvalidArbiter"


def test_fund_partial_then_full_and_overfund() -> None:
    chain = Chain()
    chain.call(create(100, 1, deposit=30))
    assert chain.error(soroban.fund(REQ, BID, 0)) == "InvalidAmount"
    assert chain.error(soroban.fund(REQ, BID, 71)) == "Overfunded"
    assert chain.error(soroban.fund(ALICE, BID, 10)) == "Unauthorized"
    e = chain.call(soroban.fund(REQ, BID, 40))
    assert e["funded_amount"] == 70 and e["status"] == "AwaitingFunding"
    e = chain.call(soroban.fund(REQ, BID, 30))
    assert e["funded_amount"] == 100 and e["status"] == "Funded"
    assert chain.error(soroban.fund(REQ, BID, 1)) == "InvalidState"
    missing = Chain()
    assert missing.error(soroban.fund(REQ, BID, 1)) == "NotFound"


def test_assign_rules() -> None:
    awaiting = Chain()
    awaiting.call(create(100, 1, deposit=10))
    assert awaiting.error(soroban.assign(REQ, BID, ALICE)) == "InvalidState"
    chain = funded(100, 2)
    assert chain.error(soroban.assign(ALICE, BID, BOB)) == "Unauthorized"  # not the requester
    assert chain.error(soroban.assign(REQ, BID, REQ)) == "Unauthorized"
    chain.call(soroban.assign(REQ, BID, ALICE))
    assert chain.escrow()["assigned_unpaid"] == 1 and chain.assignment(ALICE) == "Assigned"
    assert chain.error(soroban.assign(REQ, BID, ALICE)) == "AlreadyAssigned"
    chain.call(soroban.assign(REQ, BID, BOB))
    assert chain.error(soroban.assign(REQ, BID, CAROL)) == "PositionsExhausted"


def test_assign_rejected_at_or_after_deadline() -> None:
    chain = funded()
    chain.now = DEADLINE
    assert chain.error(soroban.assign(REQ, BID, ALICE)) == "DeadlineInPast"


def test_release_assigned_direct_and_duplicate() -> None:
    chain = funded(100, 2)
    chain.call(soroban.assign(REQ, BID, ALICE))
    e = chain.call(soroban.release(REQ, BID, ALICE))
    assert e["assigned_unpaid"] == 0 and e["payouts_made"] == 1 and e["paid_out_amount"] == 100
    assert chain.assignment(ALICE) == "Paid" and chain.balance(ALICE) == 100
    assert chain.error(soroban.release(REQ, BID, ALICE)) == "AlreadyPaid"
    e = chain.call(soroban.release(REQ, BID, BOB))  # direct payout into the free position
    assert e["status"] == "Completed" and e["paid_out_amount"] == 200
    assert chain.error(soroban.release(REQ, BID, CAROL)) == "InvalidState"


def test_release_positions_exhausted_by_assignments() -> None:
    chain = funded(100, 1)
    chain.call(soroban.assign(REQ, BID, ALICE))
    assert chain.error(soroban.release(REQ, BID, BOB)) == "PositionsExhausted"


def test_release_requires_funded_state_and_requester() -> None:
    chain = funded()
    assert chain.error(soroban.release(ALICE, BID, BOB)) == "Unauthorized"
    chain.call(soroban.request_cancel(REQ, BID))
    assert chain.error(soroban.release(REQ, BID, ALICE)) == "InvalidState"


def test_refund_awaiting_funding_directly_and_funded_requires_cancel() -> None:
    chain = Chain()
    chain.call(create(100, 1, deposit=40))
    e = chain.call(soroban.refund(REQ, BID))
    assert e["status"] == "Cancelled" and e["refunded_amount"] == 40 and chain.balance(REQ) == 40
    assert chain.error(soroban.refund(REQ, BID)) == "InvalidState"
    funded_chain = funded()
    assert funded_chain.error(soroban.refund(REQ, BID)) == "InvalidState"
    assert funded_chain.error(soroban.refund(ALICE, BID)) == "Unauthorized"


def test_refund_blocked_by_assignment_until_consent_or_deadline() -> None:
    chain = funded(100, 2)
    chain.call(soroban.assign(REQ, BID, ALICE))
    assert chain.error(soroban.consent_cancel(ALICE, BID)) == "InvalidState"  # not requested yet
    chain.call(soroban.request_cancel(REQ, BID))
    assert chain.error(soroban.request_cancel(REQ, BID)) == "InvalidState"
    assert chain.error(soroban.refund(REQ, BID)) == "AssignmentsOutstanding"
    assert chain.error(soroban.consent_cancel(BOB, BID)) == "NotAssigned"
    chain.call(soroban.consent_cancel(ALICE, BID))
    assert chain.assignment(ALICE) is None and chain.escrow()["assigned_unpaid"] == 0
    assert chain.call(soroban.refund(REQ, BID))["refunded_amount"] == 200

    late = funded()
    late.call(soroban.assign(REQ, BID, ALICE))
    late.call(soroban.request_cancel(REQ, BID))
    late.now = DEADLINE  # `now <= deadline` still blocks
    assert late.error(soroban.refund(REQ, BID)) == "AssignmentsOutstanding"
    late.now = DEADLINE + 1
    assert late.call(soroban.refund(REQ, BID))["status"] == "Cancelled"


def test_refund_after_partial_payout_returns_only_unspent_funds() -> None:
    chain = funded(100, 3)
    chain.call(soroban.release(REQ, BID, ALICE))
    chain.call(soroban.request_cancel(REQ, BID))
    e = chain.call(soroban.refund(REQ, BID))
    assert e["refunded_amount"] == 200 and e["paid_out_amount"] == 100
    assert e["paid_out_amount"] + e["refunded_amount"] <= e["funded_amount"]


def test_dispute_raise_rules() -> None:
    chain = funded(100, 2)
    assert chain.error(soroban.raise_dispute(ALICE, BID)) == "Unauthorized"  # non-party (checked first)
    assert chain.error(soroban.raise_dispute(REQ, BID)) == "NotAssigned"  # nobody to resolve for
    chain.call(soroban.assign(REQ, BID, ALICE))
    e = chain.call(soroban.raise_dispute(ALICE, BID))
    assert e["status"] == "Disputed" and e["pre_dispute_status"] == "Funded"
    assert chain.error(soroban.raise_dispute(REQ, BID)) == "InvalidState"
    missing = Chain()
    assert missing.error(soroban.raise_dispute(REQ, BID)) == "NotFound"
    awaiting = Chain()
    awaiting.call(create(100, 1, deposit=1))
    assert awaiting.error(soroban.raise_dispute(REQ, BID)) == "InvalidState"


def test_resolve_dispute_pay_unassign_and_completion() -> None:
    chain = funded(100, 2)
    chain.call(soroban.assign(REQ, BID, ALICE))
    chain.call(soroban.assign(REQ, BID, BOB))
    assert chain.error(soroban.resolve_dispute(ARB, BID, ALICE, True)) == "InvalidState"  # not disputed
    chain.call(soroban.request_cancel(REQ, BID))
    chain.call(soroban.raise_dispute(REQ, BID))
    assert chain.error(soroban.resolve_dispute(REQ, BID, ALICE, True)) == "Unauthorized"
    assert chain.error(soroban.resolve_dispute(ARB, BID, CAROL, True)) == "NotAssigned"
    e = chain.call(soroban.resolve_dispute(ARB, BID, ALICE, False))
    assert e["status"] == "CancelRequested" and e["assigned_unpaid"] == 1 and chain.assignment(ALICE) is None

    paying = funded(100, 1)
    paying.call(soroban.assign(REQ, BID, ALICE))
    paying.call(soroban.raise_dispute(ALICE, BID))
    e = paying.call(soroban.resolve_dispute(ARB, BID, ALICE, True))
    assert e["status"] == "Completed" and e["payouts_made"] == 1 and paying.balance(ALICE) == 100


def test_source_account_must_match_the_authorizing_address() -> None:
    chain = funded()
    assert chain.error(soroban.request_cancel(REQ, BID), source=ALICE) == "Unauthorized"


def test_escrows_are_isolated() -> None:
    chain = funded()
    other = bytes(reversed(range(32)))
    assert chain.error(soroban.fund(REQ, other, 1)) == "NotFound"
    chain.call(create(bid=other, deposit=0))
    assert chain.escrow()["status"] == "Funded"


def test_failed_calls_leave_the_ledger_untouched() -> None:
    chain = funded(100, 1)
    chain.call(soroban.assign(REQ, BID, ALICE))
    before = dict(chain.escrow())
    # Unfunded release: InsufficientFunds is raised after assigned_unpaid was decremented in the working copy.
    chain.ledger.rows[f"escrow:{BID.hex()}"] = {**before, "funded_amount": 50}
    with pytest.raises(ContractError) as info:
        chain.call(soroban.release(REQ, BID, ALICE))
    assert info.value.name == "InsufficientFunds"
    assert chain.escrow()["assigned_unpaid"] == 1
