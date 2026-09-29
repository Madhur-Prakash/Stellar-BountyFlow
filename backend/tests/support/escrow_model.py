"""In-memory model of the BountyEscrow Soroban contract (contracts/bounty_escrow/src/lib.rs), for tests only.

Every function, check order and error code mirrors the Rust contract (verified by tests/unit/test_escrow_model.py
against the contract's rules). The test chain in `fake_chain.py` uses it to execute signed transactions. It models
interface version 2 (milestones, the review window, M-of-N arbiters and batch releases) on the Testnet deployment
(minimum review window 60 seconds); v1 calls behave exactly as on the v1 contract.
"""

from __future__ import annotations

from typing import Any

from app.blockchain.soroban import CONTRACT_ERRORS, ContractCall, ContractError

MAX_POSITIONS = 100
MAX_ARBITERS = 10
MAX_MILESTONES = 20
MAX_BATCH = 10
DEFAULT_REVIEW_WINDOW = 7 * 86_400
MAX_REVIEW_WINDOW = 30 * 86_400
MIN_REVIEW_WINDOW = 60  # the Testnet deployment's constructor argument
I128_MAX = 2**127 - 1  # the contract's checked i128 arithmetic returns Overflow (#15) beyond this
REVIEW_OPEN = ("Funded", "CancelRequested")


def _err(code: int) -> ContractError:
    return ContractError(code, CONTRACT_ERRORS[code][1], f"Error(Contract, #{code})")


class Ledger:
    """Mutable view over the in-memory contract storage."""

    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.rows = rows
        self.dirty: set[str] = set()

    def get(self, key: str) -> dict[str, Any] | None:
        return self.rows.get(key)

    def put(self, key: str, value: dict[str, Any]) -> None:
        self.rows[key] = value
        self.dirty.add(key)

    def delete(self, key: str) -> None:
        self.rows.pop(key, None)
        self.dirty.add(key)


def _escrow_key(bid: str) -> str:
    return f"escrow:{bid}"


def _assign_key(bid: str, addr: str) -> str:
    return f"assign:{bid}:{addr}"


def _review_key(bid: str, addr: str) -> str:
    return f"review:{bid}:{addr}"


def _vote_key(bid: str, addr: str) -> str:
    return f"vote:{bid}:{addr}"


def _claimable_at(e: dict[str, Any], review: dict[str, Any]) -> int:
    if not e["clock_reset_at"]:
        return int(review["claimable_at"])
    return max(int(review["claimable_at"]), e["clock_reset_at"] + e["review_window"])


def _position_value(e: dict[str, Any]) -> int:
    if not e["milestones"]:
        return int(e["reward_per_position"])
    return sum(m["amount"] for m in e["milestones"] if not m["paid"])


def view(ledger: Ledger, call: ContractCall) -> Any:
    """Read-only functions (simulated, never committed)."""
    a = call.native
    bid = a.get("bounty_id", "")
    fn = call.function
    if fn == "version":
        return 2
    escrow = ledger.get(_escrow_key(bid))
    if fn == "get_escrow":
        if escrow is None:
            raise _err(1)
        return dict(escrow)
    if fn == "assignment":
        value = ledger.get(_assign_key(bid, a["contributor"]))
        return None if value is None else ["Assigned", "Paid"].index(value["state"])
    if fn == "review":
        review = ledger.get(_review_key(bid, a["contributor"]))
        if review is None:
            return None
        return {**review, "state": ["Pending", "ChangesRequested", "Rejected"].index(review["state"])}
    if fn == "resolution_votes":
        if escrow is None:
            raise _err(1)
        votes = []
        for arbiter in escrow["arbiters"]:
            vote = ledger.get(_vote_key(bid, arbiter))
            if vote is not None and vote["round"] == escrow["dispute_round"]:
                votes.append(
                    {
                        "arbiter": arbiter,
                        "contributor": vote["contributor"],
                        "contributor_amount": vote["contributor_amount"],
                    }
                )
        return votes
    raise ContractError(None, f"Unknown contract view {fn}")


def execute(ledger: Ledger, call: ContractCall, source: str, now: int) -> dict[str, Any]:
    """Apply a contract call to the in-memory ledger. Raises ContractError exactly like the contract."""
    a = call.native
    fn = call.function
    if call.auth_address and call.auth_address != source:
        # On-chain, only the transaction source account's authorization is provided by the wallet signature.
        raise _err(6)
    bid = a.get("bounty_id", "")
    stored = ledger.get(_escrow_key(bid))
    # Work on a copy: a call that fails half-way (e.g. InsufficientFunds after a counter update) must leave the
    # ledger untouched, exactly like a reverted contract invocation. Writes to other keys are staged the same way.
    escrow = _copy(stored) if stored is not None else None
    staged: dict[str, dict[str, Any] | None] = {}

    def get(key: str) -> dict[str, Any] | None:
        return staged[key] if key in staged else ledger.get(key)

    def put(key: str, value: dict[str, Any] | None) -> None:
        staged[key] = value

    def credit(address: str, amount: int) -> None:
        if amount <= 0:
            return
        key = f"balance:{address}"
        current = (get(key) or {}).get("stroops", 0)
        put(key, {"stroops": current + amount})

    def load_as_requester() -> dict[str, Any]:
        if escrow is None:
            raise _err(1)
        if escrow["requester"] != a["requester"]:
            raise _err(6)
        return escrow

    def positions_taken(e: dict[str, Any]) -> int:
        return int(e["payouts_made"]) + int(e["assigned_unpaid"])

    def state_of(contributor: str) -> str | None:
        return (get(_assign_key(bid, contributor)) or {}).get("state")

    def clear_review(e: dict[str, Any], contributor: str, only_milestone: int | None = None) -> None:
        review = get(_review_key(bid, contributor))
        if review is None:
            return
        if only_milestone is not None and review["milestone"] != only_milestone:
            return
        if review["state"] == "Pending":
            e["pending_reviews"] -= 1
        put(_review_key(bid, contributor), None)

    def take_position(e: dict[str, Any], contributor: str) -> None:
        state = state_of(contributor)
        if state == "Paid":
            raise _err(7)
        if state is None:
            if positions_taken(e) >= e["positions"]:
                raise _err(10)
            e["assigned_unpaid"] += 1
            put(_assign_key(bid, contributor), {"state": "Assigned"})

    def book(e: dict[str, Any], amount: int) -> None:
        if e["funded_amount"] - e["paid_out_amount"] < amount:
            raise _err(11)
        e["paid_out_amount"] += amount

    def finish(e: dict[str, Any]) -> int:
        if e["payouts_made"] != e["positions"]:
            return 0
        e["status"] = "Completed"
        leftover = e["funded_amount"] - e["paid_out_amount"] - e["refunded_amount"]
        e["refunded_amount"] += leftover
        return int(leftover)

    def complete(e: dict[str, Any], contributor: str) -> int:
        e["assigned_unpaid"] -= 1
        e["payouts_made"] += 1
        put(_assign_key(bid, contributor), {"state": "Paid"})
        return finish(e)

    def pay_position(e: dict[str, Any], contributor: str) -> tuple[int, int]:
        take_position(e, contributor)
        amount = _position_value(e)
        book(e, amount)
        for m in e["milestones"]:
            m["paid"] = True
        clear_review(e, contributor)
        return amount, complete(e, contributor)

    def pay_milestone(e: dict[str, Any], contributor: str, index: int) -> tuple[int, int]:
        if index >= len(e["milestones"]):
            raise _err(20)
        milestone = e["milestones"][index]
        if milestone["paid"]:
            raise _err(21)
        take_position(e, contributor)
        book(e, milestone["amount"])
        milestone["paid"] = True
        clear_review(e, contributor, index)
        leftover = 0
        if all(m["paid"] for m in e["milestones"]):
            clear_review(e, contributor)
            leftover = complete(e, contributor)
        return int(milestone["amount"]), leftover

    def create(terms: dict[str, Any]) -> dict[str, Any]:
        if escrow is not None:
            raise _err(2)
        reward, positions, deposit = (
            terms["reward_per_position"],
            terms["positions"],
            terms["initial_deposit"],
        )
        arbiters = list(terms["arbiters"])
        if reward <= 0:
            raise _err(3)
        if positions == 0 or positions > MAX_POSITIONS:
            raise _err(4)
        if (
            not arbiters
            or len(arbiters) > MAX_ARBITERS
            or a["requester"] in arbiters
            or len(set(arbiters)) != len(arbiters)
        ):
            raise _err(16)
        if terms["threshold"] == 0 or terms["threshold"] > len(arbiters):
            raise _err(17)
        if terms["deadline"] <= now:
            raise _err(13)
        if not MIN_REVIEW_WINDOW <= terms["review_window"] <= MAX_REVIEW_WINDOW:
            raise _err(18)
        amounts = list(terms["milestones"])
        if amounts and (
            positions != 1
            or len(amounts) > MAX_MILESTONES
            or any(m <= 0 for m in amounts)
            or sum(amounts) != reward
        ):
            raise _err(19)
        required = reward * positions
        if required > I128_MAX:
            raise _err(15)
        if deposit < 0:
            raise _err(3)
        if deposit > required:
            raise _err(12)
        status = "Funded" if deposit == required else "AwaitingFunding"
        return {
            "requester": a["requester"],
            "token": a["token"],
            "arbiter": arbiters[0],
            "reward_per_position": reward,
            "positions": positions,
            "required_amount": required,
            "funded_amount": deposit,
            "paid_out_amount": 0,
            "refunded_amount": 0,
            "payouts_made": 0,
            "assigned_unpaid": 0,
            "deadline": terms["deadline"],
            "status": status,
            "pre_dispute_status": status,
            "created_at": now,
            "arbiters": arbiters,
            "threshold": terms["threshold"],
            "review_window": terms["review_window"],
            "pending_reviews": 0,
            "dispute_round": 0,
            "clock_reset_at": 0,
            "milestones": [{"amount": m, "paid": False} for m in amounts],
        }

    def answer(new_state: str) -> dict[str, Any]:
        e = load_as_requester()
        if e["status"] not in REVIEW_OPEN:
            raise _err(5)
        review = get(_review_key(bid, a["contributor"]))
        if review is None or review["state"] != "Pending":
            raise _err(23)
        if now >= _claimable_at(e, review):
            raise _err(25)
        put(_review_key(bid, a["contributor"]), {**review, "state": new_state})
        e["pending_reviews"] -= 1
        return e

    def vote(arbiter: str, contributor: str, amount: int) -> dict[str, Any]:
        if escrow is None:
            raise _err(1)
        e = escrow
        if arbiter not in e["arbiters"]:
            raise _err(6)
        if e["status"] != "Disputed":
            raise _err(5)
        if state_of(contributor) != "Assigned":
            raise _err(9)
        if amount < 0 or amount > _position_value(e):
            raise _err(27)
        put(
            _vote_key(bid, arbiter),
            {"round": e["dispute_round"], "contributor": contributor, "contributor_amount": amount},
        )
        approvals = 0
        for member in e["arbiters"]:
            v = get(_vote_key(bid, member))
            if (
                v
                and v["round"] == e["dispute_round"]
                and v["contributor"] == contributor
                and v["contributor_amount"] == amount
            ):
                approvals += 1
        if approvals < e["threshold"]:
            return e
        for member in e["arbiters"]:
            put(_vote_key(bid, member), None)
        clear_review(e, contributor)
        leftover = 0
        if amount > 0:
            book(e, amount)
            for m in e["milestones"]:
                m["paid"] = True
            leftover = complete(e, contributor)
            credit(contributor, amount)
        else:
            put(_assign_key(bid, contributor), None)
            e["assigned_unpaid"] -= 1
        e["clock_reset_at"] = now
        if e["status"] != "Completed":
            e["status"] = e["pre_dispute_status"]
        credit(e["requester"], leftover)
        return e

    if fn == "create_escrow":
        escrow = create(
            {
                "reward_per_position": a["reward_per_position"],
                "positions": a["positions"],
                "deadline": a["deadline"],
                "initial_deposit": a["initial_deposit"],
                "arbiters": [a["arbiter"]],
                "threshold": 1,
                "review_window": DEFAULT_REVIEW_WINDOW,
                "milestones": [],
            }
        )
    elif fn == "create_escrow_v2":
        escrow = create(a)
    elif fn == "fund":
        escrow = load_as_requester()
        if escrow["status"] != "AwaitingFunding":
            raise _err(5)
        if a["amount"] <= 0:
            raise _err(3)
        total = escrow["funded_amount"] + a["amount"]
        if total > I128_MAX:
            raise _err(15)
        if total > escrow["required_amount"]:
            raise _err(12)
        escrow["funded_amount"] = total
        if total == escrow["required_amount"]:
            escrow["status"] = "Funded"
    elif fn == "assign":
        escrow = load_as_requester()
        if escrow["status"] != "Funded":
            raise _err(5)
        if now >= escrow["deadline"]:  # SEC-06 (contract source): no assignment once the deadline passed
            raise _err(13)
        if a["contributor"] == escrow["requester"]:
            raise _err(6)
        if get(_assign_key(bid, a["contributor"])) is not None:
            raise _err(8)
        if positions_taken(escrow) >= escrow["positions"]:
            raise _err(10)
        escrow["assigned_unpaid"] += 1
        put(_assign_key(bid, a["contributor"]), {"state": "Assigned"})
    elif fn == "release":
        escrow = load_as_requester()
        if escrow["status"] != "Funded":
            raise _err(5)
        amount, leftover = pay_position(escrow, a["contributor"])
        credit(a["contributor"], amount)
        credit(a["requester"], leftover)
    elif fn == "release_milestone":
        escrow = load_as_requester()
        if escrow["status"] != "Funded":
            raise _err(5)
        amount, leftover = pay_milestone(escrow, a["contributor"], a["milestone"])
        credit(a["contributor"], amount)
        credit(a["requester"], leftover)
    elif fn == "batch_release":
        escrow = load_as_requester()
        if escrow["status"] != "Funded":
            raise _err(5)
        items = a["items"]
        if not items or len(items) > MAX_BATCH:
            raise _err(28)
        payments: list[tuple[str, int]] = []
        leftover = 0
        for item in items:
            if item.get("milestone") is None:
                amount, rest = pay_position(escrow, item["contributor"])
            else:
                amount, rest = pay_milestone(escrow, item["contributor"], item["milestone"])
            payments.append((item["contributor"], amount))
            leftover += rest
        for contributor, amount in payments:
            credit(contributor, amount)
        credit(a["requester"], leftover)
    elif fn == "submit_work":
        if escrow is None:
            raise _err(1)
        if escrow["status"] not in REVIEW_OPEN:
            raise _err(5)
        if now >= escrow["deadline"]:
            raise _err(13)
        if state_of(a["contributor"]) != "Assigned":
            raise _err(9)
        milestone = a["milestone"]
        if not escrow["milestones"]:
            if milestone != 0:
                raise _err(20)
        else:
            if milestone >= len(escrow["milestones"]):
                raise _err(20)
            if escrow["milestones"][milestone]["paid"]:
                raise _err(21)
        review = get(_review_key(bid, a["contributor"]))
        if review is not None and review["state"] == "Pending":
            raise _err(22)
        if review is not None and review["state"] == "Rejected":
            raise _err(26)
        put(
            _review_key(bid, a["contributor"]),
            {
                "milestone": milestone,
                "submitted_at": now,
                "claimable_at": now + escrow["review_window"],
                "state": "Pending",
            },
        )
        escrow["pending_reviews"] += 1
    elif fn == "request_changes":
        escrow = answer("ChangesRequested")
    elif fn == "reject_submission":
        escrow = answer("Rejected")
    elif fn == "claim":
        if escrow is None:
            raise _err(1)
        if escrow["status"] not in REVIEW_OPEN:
            raise _err(5)
        review = get(_review_key(bid, a["contributor"]))
        if review is None or review["state"] != "Pending":
            raise _err(23)
        if now < _claimable_at(escrow, review):
            raise _err(24)
        if escrow["milestones"]:
            amount, leftover = pay_milestone(escrow, a["contributor"], review["milestone"])
        else:
            amount, leftover = pay_position(escrow, a["contributor"])
        credit(a["contributor"], amount)
        credit(escrow["requester"], leftover)
    elif fn == "request_cancel":
        escrow = load_as_requester()
        if escrow["status"] not in ("AwaitingFunding", "Funded"):
            raise _err(5)
        escrow["status"] = "CancelRequested"
    elif fn == "consent_cancel":
        if escrow is None:
            raise _err(1)
        if escrow["status"] != "CancelRequested":
            raise _err(5)
        if state_of(a["contributor"]) != "Assigned":
            raise _err(9)
        put(_assign_key(bid, a["contributor"]), None)
        clear_review(escrow, a["contributor"])
        escrow["assigned_unpaid"] -= 1
    elif fn == "refund":
        escrow = load_as_requester()
        if escrow["status"] not in ("AwaitingFunding", "CancelRequested"):
            raise _err(5)
        if escrow["assigned_unpaid"] != 0 and now <= escrow["deadline"]:
            raise _err(14)
        if escrow["pending_reviews"] != 0:
            raise _err(22)
        amount = escrow["funded_amount"] - escrow["paid_out_amount"] - escrow["refunded_amount"]
        escrow["refunded_amount"] += amount
        escrow["status"] = "Cancelled"
        credit(a["requester"], amount)
    elif fn == "raise_dispute":
        if escrow is None:
            raise _err(1)
        caller = a["caller"]
        is_party = caller == escrow["requester"] or state_of(caller) == "Assigned"
        if not is_party:
            raise _err(6)
        if escrow["status"] not in ("Funded", "CancelRequested"):
            raise _err(5)
        if escrow["assigned_unpaid"] == 0:  # SEC-05 (contract source): the arbiter needs someone to resolve
            raise _err(9)
        escrow["pre_dispute_status"] = escrow["status"]
        escrow["status"] = "Disputed"
        escrow["dispute_round"] += 1
    elif fn == "resolve_dispute":
        if escrow is None:
            raise _err(1)
        amount = _position_value(escrow) if a["pay_contributor"] else 0
        escrow = vote(a["arbiter"], a["contributor"], amount)
    elif fn == "vote_resolution":
        escrow = vote(a["arbiter"], a["contributor"], a["contributor_amount"])
    else:
        raise ContractError(None, f"Unknown contract function {fn}")

    assert escrow is not None
    for key, value in staged.items():
        if value is None:
            ledger.delete(key)
        else:
            ledger.put(key, value)
    ledger.put(_escrow_key(bid), escrow)
    return _copy(escrow)


def _copy(escrow: dict[str, Any]) -> dict[str, Any]:
    out = dict(escrow)
    if "milestones" in out:
        out["milestones"] = [dict(m) for m in out["milestones"]]
    if "arbiters" in out:
        out["arbiters"] = list(out["arbiters"])
    return out
