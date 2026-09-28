"""In-memory model of the BountyEscrow Soroban contract (contracts/bounty_escrow/src/lib.rs), for tests only.

Every function, check order and error code mirrors the Rust contract (verified by tests/unit/test_escrow_model.py
against the contract's rules). The test chain in `fake_chain.py` uses it to execute signed transactions.
"""

from __future__ import annotations

from typing import Any

from app.blockchain.soroban import CONTRACT_ERRORS, ContractCall, ContractError

MAX_POSITIONS = 100
I128_MAX = 2**127 - 1  # the contract's checked i128 arithmetic returns Overflow (#15) beyond this


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
    # ledger untouched, exactly like a reverted contract invocation.
    escrow = dict(stored) if stored is not None else None

    def load_as_requester() -> dict[str, Any]:
        if escrow is None:
            raise _err(1)
        if escrow["requester"] != a["requester"]:
            raise _err(6)
        return escrow

    def positions_taken(e: dict[str, Any]) -> int:
        return int(e["payouts_made"]) + int(e["assigned_unpaid"])

    def pay(e: dict[str, Any], contributor: str) -> None:
        available = e["funded_amount"] - e["paid_out_amount"]
        if available < e["reward_per_position"]:
            raise _err(11)
        e["paid_out_amount"] += e["reward_per_position"]
        e["payouts_made"] += 1
        ledger.put(_assign_key(bid, contributor), {"state": "Paid"})
        _credit(ledger, contributor, e["reward_per_position"])
        if e["payouts_made"] == e["positions"]:
            e["status"] = "Completed"

    if fn == "create_escrow":
        if escrow is not None:
            raise _err(2)
        reward, positions, deposit = a["reward_per_position"], a["positions"], a["initial_deposit"]
        if reward <= 0:
            raise _err(3)
        if positions == 0 or positions > MAX_POSITIONS:
            raise _err(4)
        if a["arbiter"] == a["requester"]:
            raise _err(16)
        if a["deadline"] <= now:
            raise _err(13)
        required = reward * positions
        if required > I128_MAX:
            raise _err(15)
        if deposit < 0:
            raise _err(3)
        if deposit > required:
            raise _err(12)
        status = "Funded" if deposit == required else "AwaitingFunding"
        escrow = {
            "requester": a["requester"],
            "token": a["token"],
            "arbiter": a["arbiter"],
            "reward_per_position": reward,
            "positions": positions,
            "required_amount": required,
            "funded_amount": deposit,
            "paid_out_amount": 0,
            "refunded_amount": 0,
            "payouts_made": 0,
            "assigned_unpaid": 0,
            "deadline": a["deadline"],
            "status": status,
            "pre_dispute_status": status,
            "created_at": now,
        }
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
        if ledger.get(_assign_key(bid, a["contributor"])) is not None:
            raise _err(8)
        if positions_taken(escrow) >= escrow["positions"]:
            raise _err(10)
        escrow["assigned_unpaid"] += 1
        ledger.put(_assign_key(bid, a["contributor"]), {"state": "Assigned"})
    elif fn == "release":
        escrow = load_as_requester()
        if escrow["status"] != "Funded":
            raise _err(5)
        state = (ledger.get(_assign_key(bid, a["contributor"])) or {}).get("state")
        if state == "Paid":
            raise _err(7)
        if state == "Assigned":
            escrow["assigned_unpaid"] -= 1
        elif positions_taken(escrow) >= escrow["positions"]:
            raise _err(10)
        pay(escrow, a["contributor"])
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
        if (ledger.get(_assign_key(bid, a["contributor"])) or {}).get("state") != "Assigned":
            raise _err(9)
        ledger.delete(_assign_key(bid, a["contributor"]))
        escrow["assigned_unpaid"] -= 1
    elif fn == "refund":
        escrow = load_as_requester()
        if escrow["status"] not in ("AwaitingFunding", "CancelRequested"):
            raise _err(5)
        if escrow["assigned_unpaid"] != 0 and now <= escrow["deadline"]:
            raise _err(14)
        amount = escrow["funded_amount"] - escrow["paid_out_amount"] - escrow["refunded_amount"]
        escrow["refunded_amount"] += amount
        escrow["status"] = "Cancelled"
        _credit(ledger, a["requester"], amount)
    elif fn == "raise_dispute":
        if escrow is None:
            raise _err(1)
        caller = a["caller"]
        is_party = (
            caller == escrow["requester"]
            or (ledger.get(_assign_key(bid, caller)) or {}).get("state") == "Assigned"
        )
        if not is_party:
            raise _err(6)
        if escrow["status"] not in ("Funded", "CancelRequested"):
            raise _err(5)
        if escrow["assigned_unpaid"] == 0:  # SEC-05 (contract source): the arbiter needs someone to resolve
            raise _err(9)
        escrow["pre_dispute_status"] = escrow["status"]
        escrow["status"] = "Disputed"
    elif fn == "resolve_dispute":
        if escrow is None:
            raise _err(1)
        if escrow["arbiter"] != a["arbiter"]:
            raise _err(6)
        if escrow["status"] != "Disputed":
            raise _err(5)
        if (ledger.get(_assign_key(bid, a["contributor"])) or {}).get("state") != "Assigned":
            raise _err(9)
        escrow["assigned_unpaid"] -= 1
        if a["pay_contributor"]:
            pay(escrow, a["contributor"])
        else:
            ledger.delete(_assign_key(bid, a["contributor"]))
        if escrow["status"] != "Completed":
            escrow["status"] = escrow["pre_dispute_status"]
    else:
        raise ContractError(None, f"Unknown contract function {fn}")

    ledger.put(_escrow_key(bid), escrow)
    return dict(escrow)


def _credit(ledger: Ledger, address: str, amount: int) -> None:
    key = f"balance:{address}"
    current = (ledger.get(key) or {}).get("stroops", 0)
    ledger.put(key, {"stroops": current + amount})
