"""Escrow v2 fidelity of the test escrow model (tests/support/escrow_model.py) against the contract
(contracts/bounty_escrow/src/lib.rs, tests in src/test.rs): milestones, the review window and claims, M-of-N
arbiter votes with split resolutions, and atomic batch releases."""

from __future__ import annotations

from typing import Any

import pytest

from app.blockchain import soroban
from app.blockchain.soroban import ContractCall, ContractError, EscrowTerms, PayoutLeg
from app.modules.escrow import review_clock
from app.modules.payments.models import EscrowState
from app.modules.submissions.models import OnchainReviewState
from tests.support.escrow_model import Ledger, execute, view

NOW = 1_800_000_000
DEADLINE = NOW + 30 * 86400
WINDOW = 2 * 86400
REQ = "G-REQUESTER"
ARB, ARB2, ARB3 = "G-ARBITER", "G-ARBITER-2", "G-ARBITER-3"
ALICE, BOB, CAROL = "G-ALICE", "G-BOB", "G-CAROL"
TOKEN = "C-NATIVE"
BID = bytes(range(32))


class Chain:
    def __init__(self) -> None:
        self.ledger = Ledger({})
        self.now = NOW

    def call(self, call: ContractCall) -> dict[str, Any]:
        return execute(self.ledger, call, call.auth_address or "", self.now)

    def error(self, call: ContractCall) -> str:
        with pytest.raises(ContractError) as info:
            self.call(call)
        return info.value.name

    def escrow(self) -> dict[str, Any]:
        value = self.ledger.get(f"escrow:{BID.hex()}")
        assert value is not None
        return value

    def state(self, who: str) -> str | None:
        value = self.ledger.get(f"assign:{BID.hex()}:{who}")
        return None if value is None else value["state"]

    def review(self, who: str) -> Any:
        return view(self.ledger, soroban.review(BID, who))

    def balance(self, who: str) -> int:
        return int((self.ledger.get(f"balance:{who}") or {}).get("stroops", 0))


def terms(**kw: Any) -> EscrowTerms:
    values: dict[str, Any] = {
        "reward_per_position": 1000,
        "positions": 1,
        "deadline": DEADLINE,
        "initial_deposit": None,
        "arbiters": (ARB,),
        "threshold": 1,
        "review_window": WINDOW,
        "milestones": (),
    }
    values.update(kw)
    if values["initial_deposit"] is None:
        values["initial_deposit"] = values["reward_per_position"] * values["positions"]
    return EscrowTerms(**values)


def created(**kw: Any) -> Chain:
    chain = Chain()
    chain.call(soroban.create_escrow_v2(REQ, BID, TOKEN, terms(**kw)))
    return chain


def test_v1_create_reads_as_one_arbiter_and_the_default_window() -> None:
    chain = Chain()
    e = chain.call(soroban.create_escrow(REQ, BID, TOKEN, 100, 1, ARB, DEADLINE, 100))
    assert e["arbiters"] == [ARB] and e["threshold"] == 1 and e["review_window"] == 7 * 86400
    assert e["milestones"] == [] and e["pending_reviews"] == 0


def test_create_v2_validation_order() -> None:
    chain = Chain()
    bad = [
        (terms(arbiters=()), "InvalidArbiter"),
        (terms(arbiters=(ARB, ARB)), "InvalidArbiter"),
        (terms(arbiters=(ARB, REQ)), "InvalidArbiter"),
        (terms(threshold=2), "InvalidThreshold"),
        (terms(threshold=0), "InvalidThreshold"),
        (terms(review_window=59), "InvalidReviewWindow"),
        (terms(review_window=30 * 86400 + 1), "InvalidReviewWindow"),
        (terms(positions=2, milestones=(1000, 1000)), "InvalidMilestones"),
        (terms(milestones=(400, 500)), "InvalidMilestones"),
        (terms(milestones=(1000, 0)), "InvalidMilestones"),
    ]
    for t, name in bad:
        assert chain.error(soroban.create_escrow_v2(REQ, BID, TOKEN, t)) == name
    e = chain.call(soroban.create_escrow_v2(REQ, BID, TOKEN, terms(milestones=(400, 600))))
    assert [m["amount"] for m in e["milestones"]] == [400, 600]


def test_milestones_pay_in_any_order_and_the_last_completes() -> None:
    chain = created(milestones=(200, 300, 500))
    chain.call(soroban.assign(REQ, BID, ALICE))
    e = chain.call(soroban.release_milestone(REQ, BID, ALICE, 1))
    assert e["paid_out_amount"] == 300 and e["payouts_made"] == 0 and chain.state(ALICE) == "Assigned"
    assert chain.error(soroban.release_milestone(REQ, BID, ALICE, 1)) == "MilestoneAlreadyPaid"
    assert chain.error(soroban.release_milestone(REQ, BID, ALICE, 3)) == "InvalidMilestone"
    assert chain.error(soroban.release_milestone(REQ, BID, BOB, 0)) == "PositionsExhausted"
    chain.call(soroban.release_milestone(REQ, BID, ALICE, 0))
    e = chain.call(soroban.release_milestone(REQ, BID, ALICE, 2))
    assert e["status"] == "Completed" and chain.state(ALICE) == "Paid" and chain.balance(ALICE) == 1000


def test_claim_timing_and_requester_answers() -> None:
    chain = created()
    chain.call(soroban.assign(REQ, BID, ALICE))
    e = chain.call(soroban.submit_work(ALICE, BID, 0))
    assert e["pending_reviews"] == 1
    assert chain.review(ALICE)["claimable_at"] == NOW + WINDOW
    assert chain.error(soroban.submit_work(ALICE, BID, 0)) == "ReviewPending"
    chain.now = NOW + WINDOW - 1
    assert chain.error(soroban.claim(ALICE, BID)) == "ReviewWindowOpen"
    chain.call(soroban.request_changes(REQ, BID, ALICE))  # the last second still counts
    assert chain.review(ALICE)["state"] == 1  # ChangesRequested
    assert chain.error(soroban.claim(ALICE, BID)) == "NoPendingReview"
    chain.call(soroban.submit_work(ALICE, BID, 0))
    chain.now += WINDOW
    assert chain.error(soroban.request_changes(REQ, BID, ALICE)) == "ReviewWindowElapsed"
    assert chain.error(soroban.reject_submission(REQ, BID, ALICE)) == "ReviewWindowElapsed"
    e = chain.call(soroban.claim(ALICE, BID))
    assert e["status"] == "Completed" and e["pending_reviews"] == 0 and chain.balance(ALICE) == 1000
    assert chain.review(ALICE) is None


def test_rejection_is_final_and_refund_waits_for_pending_reviews() -> None:
    chain = created(positions=2)
    chain.call(soroban.assign(REQ, BID, ALICE))
    chain.call(soroban.assign(REQ, BID, BOB))
    chain.call(soroban.submit_work(ALICE, BID, 0))
    chain.call(soroban.reject_submission(REQ, BID, ALICE))
    assert chain.error(soroban.submit_work(ALICE, BID, 0)) == "WorkRejected"
    chain.call(soroban.submit_work(BOB, BID, 0))
    chain.call(soroban.request_cancel(REQ, BID))
    chain.now = DEADLINE + 1
    assert chain.error(soroban.refund(REQ, BID)) == "ReviewPending"


def test_dispute_freezes_claims_and_resets_the_clock() -> None:
    chain = created(positions=2)
    chain.call(soroban.assign(REQ, BID, ALICE))
    chain.call(soroban.assign(REQ, BID, BOB))
    chain.call(soroban.submit_work(ALICE, BID, 0))
    chain.call(soroban.raise_dispute(REQ, BID))
    chain.now = NOW + WINDOW
    assert chain.error(soroban.claim(ALICE, BID)) == "InvalidState"
    chain.now = NOW + WINDOW + 100
    e = chain.call(soroban.resolve_dispute(ARB, BID, BOB, False))
    assert e["clock_reset_at"] == NOW + WINDOW + 100
    chain.now = NOW + 2 * WINDOW + 99
    assert chain.error(soroban.claim(ALICE, BID)) == "ReviewWindowOpen"
    chain.now += 1
    chain.call(soroban.claim(ALICE, BID))
    assert chain.balance(ALICE) == 1000


def test_two_of_three_split_resolution() -> None:
    chain = created(arbiters=(ARB, ARB2, ARB3), threshold=2)
    chain.call(soroban.assign(REQ, BID, ALICE))
    chain.call(soroban.raise_dispute(ALICE, BID))
    assert chain.error(soroban.vote_resolution(REQ, BID, ALICE, 600)) == "Unauthorized"
    assert chain.error(soroban.vote_resolution(ARB, BID, ALICE, 1001)) == "InvalidResolution"
    assert chain.call(soroban.vote_resolution(ARB, BID, ALICE, 600))["status"] == "Disputed"
    assert chain.call(soroban.vote_resolution(ARB2, BID, ALICE, 500))["status"] == "Disputed"
    votes = view(chain.ledger, soroban.resolution_votes(BID))
    assert [(v["arbiter"], v["contributor_amount"]) for v in votes] == [(ARB, 600), (ARB2, 500)]
    e = chain.call(soroban.vote_resolution(ARB3, BID, ALICE, 600))
    assert e["status"] == "Completed" and e["paid_out_amount"] == 600 and e["refunded_amount"] == 400
    assert chain.balance(ALICE) == 600 and chain.balance(REQ) == 400
    assert view(chain.ledger, soroban.resolution_votes(BID)) == []


def test_batch_release_is_atomic() -> None:
    chain = created(positions=3)
    chain.call(soroban.assign(REQ, BID, ALICE))
    chain.call(soroban.assign(REQ, BID, BOB))
    chain.call(soroban.release(REQ, BID, CAROL))
    before = dict(chain.escrow())
    legs = [PayoutLeg(ALICE), PayoutLeg(BOB), PayoutLeg(CAROL)]
    assert chain.error(soroban.batch_release(REQ, BID, legs)) == "AlreadyPaid"
    assert chain.escrow() == before and chain.balance(ALICE) == 0 and chain.state(ALICE) == "Assigned"
    e = chain.call(soroban.batch_release(REQ, BID, legs[:2]))
    assert e["status"] == "Completed" and chain.balance(ALICE) == chain.balance(BOB) == 1000
    assert chain.error(soroban.batch_release(REQ, BID, [])) == "InvalidState"


def test_review_clock_rules_mirror_the_contract() -> None:
    assert review_clock.effective_claimable_at(100, None, 50) == 100
    assert review_clock.effective_claimable_at(100, 80, 50) == 130
    assert review_clock.effective_claimable_at(200, 80, 50) == 200
    assert review_clock.can_move(None, OnchainReviewState.PENDING)
    assert review_clock.can_move(OnchainReviewState.CHANGES_REQUESTED, OnchainReviewState.PENDING)
    assert not review_clock.can_move(OnchainReviewState.REJECTED, OnchainReviewState.PENDING)
    assert not review_clock.can_move(OnchainReviewState.PAID, OnchainReviewState.PENDING)
    review_clock.check_record(EscrowState.FUNDED, None, now=10, deadline=20)
    with pytest.raises(Exception, match="deadline"):
        review_clock.check_record(EscrowState.FUNDED, None, now=20, deadline=20)
    with pytest.raises(Exception, match="rejected"):
        review_clock.check_record(EscrowState.FUNDED, OnchainReviewState.REJECTED, now=10, deadline=20)
    review_clock.check_answer(EscrowState.CANCEL_REQUESTED, OnchainReviewState.PENDING, now=99, opens_at=100)
    with pytest.raises(Exception, match="passed"):
        review_clock.check_answer(EscrowState.FUNDED, OnchainReviewState.PENDING, now=100, opens_at=100)
    review_clock.check_claim(EscrowState.FUNDED, OnchainReviewState.PENDING, now=100, opens_at=100)
    with pytest.raises(Exception, match="not passed"):
        review_clock.check_claim(EscrowState.FUNDED, OnchainReviewState.PENDING, now=99, opens_at=100)
    with pytest.raises(Exception, match="disputed"):
        review_clock.check_claim(EscrowState.DISPUTED, OnchainReviewState.PENDING, now=100, opens_at=100)
