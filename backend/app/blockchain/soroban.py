"""Encoding of BountyEscrow contract invocations and decoding of contract state and errors.

The contract interface is defined in contracts/bounty_escrow (see contracts/README.md).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from stellar_sdk import Address, scval
from stellar_sdk import xdr as stellar_xdr

ESCROW_STATUSES = ["AwaitingFunding", "Funded", "CancelRequested", "Disputed", "Completed", "Cancelled"]

# contracts/bounty_escrow/src/errors.rs
CONTRACT_ERRORS: dict[int, tuple[str, str]] = {
    1: ("NotFound", "The escrow for this bounty does not exist on-chain."),
    2: ("AlreadyExists", "An escrow for this bounty already exists on-chain."),
    3: ("InvalidAmount", "The amount is invalid."),
    4: ("InvalidPositions", "The number of positions is invalid."),
    5: ("InvalidState", "The escrow is not in a state that allows this action."),
    6: ("Unauthorized", "This wallet is not authorized to perform this action on the escrow."),
    7: ("AlreadyPaid", "This contributor has already been paid for this bounty."),
    8: ("AlreadyAssigned", "This contributor is already assigned on-chain."),
    9: ("NotAssigned", "This contributor is not assigned on-chain."),
    10: ("PositionsExhausted", "All positions for this bounty are already filled or paid."),
    11: ("InsufficientFunds", "The escrow does not hold enough funds for this payout."),
    12: ("Overfunded", "This deposit would exceed the escrow's required amount."),
    13: ("DeadlineInPast", "The escrow deadline must be in the future."),
    14: (
        "AssignmentsOutstanding",
        "Assigned contributors must consent before a refund (or the deadline must pass).",
    ),
    15: ("Overflow", "Arithmetic overflow."),
    16: ("InvalidArbiter", "The arbiter must be different from the requester."),
}

_CONTRACT_ERROR_RE = re.compile(r"Error\(Contract, #(\d+)\)")


def onchain_bounty_id(bounty_id: uuid.UUID, salt: bytes | None = None) -> bytes:
    """32-byte identifier used as the contract's BytesN<32> bounty key.

    Security: the escrow contract is permissionless, so an id derivable from the public bounty UUID alone lets
    anyone pre-create ("squat") a bounty's escrow and block its funding. New escrows therefore pass a random
    ``salt``; the resulting id is stored on the ``bounty_escrows`` row, which stays the source of truth."""
    return hashlib.sha256(b"bountyflow:bounty:" + bounty_id.bytes + (salt or b"")).digest()


def new_onchain_bounty_id(bounty_id: uuid.UUID) -> bytes:
    """A fresh, unpredictable escrow id for ``bounty_id`` (see :func:`onchain_bounty_id`)."""
    return onchain_bounty_id(bounty_id, secrets.token_bytes(16))


@dataclass(frozen=True)
class ContractCall:
    """A contract invocation: XDR arguments (encoded on demand) plus the same arguments as Python values, which
    are recorded on the transaction row and used to verify the on-chain escrow matches what was prepared."""

    function: str
    encode: Callable[[], list[stellar_xdr.SCVal]]
    native: dict[str, Any] = field(default_factory=dict)
    auth_address: str | None = None  # the address whose require_auth() the call triggers

    @property
    def args(self) -> list[stellar_xdr.SCVal]:
        return self.encode()


def _bid(bid: bytes) -> stellar_xdr.SCVal:
    assert len(bid) == 32
    return scval.to_bytes(bid)


def create_escrow(
    requester: str,
    bid: bytes,
    token: str,
    reward_per_position: int,
    positions: int,
    arbiter: str,
    deadline: int,
    initial_deposit: int,
) -> ContractCall:
    return ContractCall(
        "create_escrow",
        lambda: [
            scval.to_address(requester),
            _bid(bid),
            scval.to_address(token),
            scval.to_int128(reward_per_position),
            scval.to_uint32(positions),
            scval.to_address(arbiter),
            scval.to_uint64(deadline),
            scval.to_int128(initial_deposit),
        ],
        {
            "requester": requester,
            "bounty_id": bid.hex(),
            "token": token,
            "reward_per_position": reward_per_position,
            "positions": positions,
            "arbiter": arbiter,
            "deadline": deadline,
            "initial_deposit": initial_deposit,
        },
        auth_address=requester,
    )


def fund(requester: str, bid: bytes, amount: int) -> ContractCall:
    return ContractCall(
        "fund",
        lambda: [scval.to_address(requester), _bid(bid), scval.to_int128(amount)],
        {"requester": requester, "bounty_id": bid.hex(), "amount": amount},
        auth_address=requester,
    )


def _party_call(
    function: str, party_key: str, party: str, bid: bytes, extra: str | None = None
) -> ContractCall:
    native: dict[str, Any] = {party_key: party, "bounty_id": bid.hex()}
    if extra is not None:
        native["contributor"] = extra

    def encode() -> list[stellar_xdr.SCVal]:
        args = [scval.to_address(party), _bid(bid)]
        if extra is not None:
            args.append(scval.to_address(extra))
        return args

    return ContractCall(function, encode, native, auth_address=party)


def assign(requester: str, bid: bytes, contributor: str) -> ContractCall:
    return _party_call("assign", "requester", requester, bid, contributor)


def release(requester: str, bid: bytes, contributor: str) -> ContractCall:
    return _party_call("release", "requester", requester, bid, contributor)


def request_cancel(requester: str, bid: bytes) -> ContractCall:
    return _party_call("request_cancel", "requester", requester, bid)


def consent_cancel(contributor: str, bid: bytes) -> ContractCall:
    return _party_call("consent_cancel", "contributor", contributor, bid)


def refund(requester: str, bid: bytes) -> ContractCall:
    return _party_call("refund", "requester", requester, bid)


def raise_dispute(caller: str, bid: bytes) -> ContractCall:
    return _party_call("raise_dispute", "caller", caller, bid)


def resolve_dispute(arbiter: str, bid: bytes, contributor: str, pay_contributor: bool) -> ContractCall:
    return ContractCall(
        "resolve_dispute",
        lambda: [
            scval.to_address(arbiter),
            _bid(bid),
            scval.to_address(contributor),
            scval.to_bool(pay_contributor),
        ],
        {
            "arbiter": arbiter,
            "bounty_id": bid.hex(),
            "contributor": contributor,
            "pay_contributor": pay_contributor,
        },
        auth_address=arbiter,
    )


def get_escrow(bid: bytes) -> ContractCall:
    return ContractCall("get_escrow", lambda: [_bid(bid)], {"bounty_id": bid.hex()})


def assignment(bid: bytes, contributor: str) -> ContractCall:
    return ContractCall(
        "assignment",
        lambda: [_bid(bid), scval.to_address(contributor)],
        {"bounty_id": bid.hex(), "contributor": contributor},
    )


@dataclass(frozen=True)
class EscrowSnapshot:
    """Decoded on-chain `Escrow` struct. Amounts are integer stroops."""

    requester: str
    token: str
    arbiter: str
    reward_per_position: int
    positions: int
    required_amount: int
    funded_amount: int
    paid_out_amount: int
    refunded_amount: int
    payouts_made: int
    assigned_unpaid: int
    deadline: int
    status: str
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _addr(value: Any) -> str:
    if isinstance(value, Address):
        return value.address
    return str(value)


def _status(value: Any) -> str:
    if isinstance(value, int):
        return ESCROW_STATUSES[value]
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value)


def decode_escrow(native: dict[str, Any]) -> EscrowSnapshot:
    return EscrowSnapshot(
        requester=_addr(native["requester"]),
        token=_addr(native["token"]),
        arbiter=_addr(native["arbiter"]),
        reward_per_position=int(native["reward_per_position"]),
        positions=int(native["positions"]),
        required_amount=int(native["required_amount"]),
        funded_amount=int(native["funded_amount"]),
        paid_out_amount=int(native["paid_out_amount"]),
        refunded_amount=int(native["refunded_amount"]),
        payouts_made=int(native["payouts_made"]),
        assigned_unpaid=int(native["assigned_unpaid"]),
        deadline=int(native["deadline"]),
        status=_status(native["status"]),
        created_at=int(native.get("created_at", 0)),
    )


def decode_assignment(native: Any) -> str | None:
    """`Option<AssignmentState>` → "Assigned" | "Paid" | None."""
    if native is None:
        return None
    if isinstance(native, int):
        return ["Assigned", "Paid"][native]
    if isinstance(native, list) and native:
        return str(native[0])
    return str(native)


class ContractError(Exception):
    def __init__(self, code: int | None, message: str, raw: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.name = CONTRACT_ERRORS.get(code, ("Unknown", ""))[0] if code else "Unknown"
        self.message = message
        self.raw = raw


def parse_contract_error(raw: str) -> ContractError:
    match = _CONTRACT_ERROR_RE.search(raw or "")
    if match:
        code = int(match.group(1))
        _name, message = CONTRACT_ERRORS.get(code, ("Unknown", f"Contract error #{code}."))
        # SAC (token) errors also surface as Error(Contract, #n) but from the token contract.
        if "balance" in raw.lower() and code not in (11,):
            return ContractError(code, "Insufficient XLM balance for this transaction.", raw)
        return ContractError(code, message, raw)
    lowered = (raw or "").lower()
    if "balance" in lowered or "underfunded" in lowered:
        return ContractError(None, "Insufficient XLM balance for this transaction.", raw)
    if "trustline" in lowered:
        return ContractError(None, "The account is missing a required trustline.", raw)
    return ContractError(None, "The contract rejected this transaction during simulation.", raw)
