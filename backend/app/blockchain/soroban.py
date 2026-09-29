"""Encoding of BountyEscrow contract invocations and decoding of contract state and errors.

The contract interface is defined in contracts/bounty_escrow (see contracts/README.md). Interface version 2 adds
milestones, the review window (``submit_work`` / ``claim``), M-of-N arbiters, ``batch_release`` and ``upgrade``;
every v1 function keeps its name and arguments. A call carries the contract id of the bounty's own escrow
(``ContractCall.contract_id``), so escrows created on the v1 deployment keep being served by it.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from stellar_sdk import Address, scval
from stellar_sdk import xdr as stellar_xdr

ESCROW_STATUSES = ["AwaitingFunding", "Funded", "CancelRequested", "Disputed", "Completed", "Cancelled"]
REVIEW_STATES = ["Pending", "ChangesRequested", "Rejected"]

# contracts/bounty_escrow/src/lib.rs (v2)
DEFAULT_REVIEW_WINDOW = 7 * 86_400  # what `create_escrow` (v1 arguments) uses
MAX_REVIEW_WINDOW = 30 * 86_400
MAX_ARBITERS = 10
MAX_MILESTONES = 20
MAX_BATCH = 10

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
    17: ("InvalidThreshold", "The arbiter threshold must be between 1 and the number of arbiters."),
    18: ("InvalidReviewWindow", "The review window is outside what this contract allows."),
    19: ("InvalidMilestones", "Milestones need a single position and must add up to the reward."),
    20: ("InvalidMilestone", "This milestone does not exist on the escrow."),
    21: ("MilestoneAlreadyPaid", "This milestone has already been paid."),
    22: ("ReviewPending", "Submitted work is waiting for an answer from the requester."),
    23: ("NoPendingReview", "There is no submission waiting for review on-chain."),
    24: ("ReviewWindowOpen", "The review window has not passed yet."),
    25: ("ReviewWindowElapsed", "The review window has passed, so the contributor can claim the payment."),
    26: ("WorkRejected", "The requester rejected this work on-chain. Raise a dispute to continue."),
    27: ("InvalidResolution", "The resolution amount is more than the contributor's open reward."),
    28: ("InvalidBatch", "A batch release needs between 1 and 10 payments."),
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
    # The escrow contract to call. None means the configured SOROBAN_CONTRACT_ID.
    contract_id: str | None = None

    @property
    def args(self) -> list[stellar_xdr.SCVal]:
        return self.encode()


def on_contract(call: ContractCall, contract_id: str | None) -> ContractCall:
    """The same call, addressed to ``contract_id`` (a bounty's own escrow contract)."""
    return replace(call, contract_id=contract_id) if contract_id else call


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


# --- v2 -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EscrowTerms:
    """Arguments of ``create_escrow_v2`` beyond the requester, escrow id and token."""

    reward_per_position: int
    positions: int
    deadline: int
    initial_deposit: int
    arbiters: tuple[str, ...]
    threshold: int
    review_window: int
    milestones: tuple[int, ...] = ()

    def native(self) -> dict[str, Any]:
        return {
            "reward_per_position": self.reward_per_position,
            "positions": self.positions,
            "deadline": self.deadline,
            "initial_deposit": self.initial_deposit,
            "arbiters": list(self.arbiters),
            "threshold": self.threshold,
            "review_window": self.review_window,
            "milestones": list(self.milestones),
        }

    def to_scval(self) -> stellar_xdr.SCVal:
        return scval.to_struct(
            {
                "reward_per_position": scval.to_int128(self.reward_per_position),
                "positions": scval.to_uint32(self.positions),
                "deadline": scval.to_uint64(self.deadline),
                "initial_deposit": scval.to_int128(self.initial_deposit),
                "arbiters": scval.to_vec([scval.to_address(a) for a in self.arbiters]),
                "threshold": scval.to_uint32(self.threshold),
                "review_window": scval.to_uint64(self.review_window),
                "milestones": scval.to_vec([scval.to_int128(m) for m in self.milestones]),
            }
        )


def create_escrow_v2(requester: str, bid: bytes, token: str, terms: EscrowTerms) -> ContractCall:
    return ContractCall(
        "create_escrow_v2",
        lambda: [scval.to_address(requester), _bid(bid), scval.to_address(token), terms.to_scval()],
        {
            "requester": requester,
            "bounty_id": bid.hex(),
            "token": token,
            # Flattened like the v1 arguments, so authenticity checks read both creation calls the same way.
            "arbiter": terms.arbiters[0] if terms.arbiters else "",
            **terms.native(),
        },
        auth_address=requester,
    )


def release_milestone(requester: str, bid: bytes, contributor: str, milestone: int) -> ContractCall:
    return ContractCall(
        "release_milestone",
        lambda: [
            scval.to_address(requester),
            _bid(bid),
            scval.to_address(contributor),
            scval.to_uint32(milestone),
        ],
        {"requester": requester, "bounty_id": bid.hex(), "contributor": contributor, "milestone": milestone},
        auth_address=requester,
    )


@dataclass(frozen=True)
class PayoutLeg:
    """One leg of ``batch_release``: a whole position, or one milestone (``milestone`` set)."""

    contributor: str
    milestone: int | None = None

    def to_scval(self) -> stellar_xdr.SCVal:
        if self.milestone is None:
            return scval.to_enum("Position", scval.to_address(self.contributor))
        return scval.to_enum(
            "Milestone", [scval.to_address(self.contributor), scval.to_uint32(self.milestone)]
        )

    def native(self) -> dict[str, Any]:
        return {"contributor": self.contributor, "milestone": self.milestone}


def batch_release(requester: str, bid: bytes, legs: list[PayoutLeg]) -> ContractCall:
    return ContractCall(
        "batch_release",
        lambda: [scval.to_address(requester), _bid(bid), scval.to_vec([leg.to_scval() for leg in legs])],
        {"requester": requester, "bounty_id": bid.hex(), "items": [leg.native() for leg in legs]},
        auth_address=requester,
    )


def submit_work(contributor: str, bid: bytes, milestone: int) -> ContractCall:
    return ContractCall(
        "submit_work",
        lambda: [scval.to_address(contributor), _bid(bid), scval.to_uint32(milestone)],
        {"contributor": contributor, "bounty_id": bid.hex(), "milestone": milestone},
        auth_address=contributor,
    )


def request_changes(requester: str, bid: bytes, contributor: str) -> ContractCall:
    return _party_call("request_changes", "requester", requester, bid, contributor)


def reject_submission(requester: str, bid: bytes, contributor: str) -> ContractCall:
    return _party_call("reject_submission", "requester", requester, bid, contributor)


def claim(contributor: str, bid: bytes) -> ContractCall:
    return _party_call("claim", "contributor", contributor, bid)


def vote_resolution(arbiter: str, bid: bytes, contributor: str, contributor_amount: int) -> ContractCall:
    return ContractCall(
        "vote_resolution",
        lambda: [
            scval.to_address(arbiter),
            _bid(bid),
            scval.to_address(contributor),
            scval.to_int128(contributor_amount),
        ],
        {
            "arbiter": arbiter,
            "bounty_id": bid.hex(),
            "contributor": contributor,
            "contributor_amount": contributor_amount,
        },
        auth_address=arbiter,
    )


def review(bid: bytes, contributor: str) -> ContractCall:
    return ContractCall(
        "review",
        lambda: [_bid(bid), scval.to_address(contributor)],
        {"bounty_id": bid.hex(), "contributor": contributor},
    )


def resolution_votes(bid: bytes) -> ContractCall:
    return ContractCall("resolution_votes", lambda: [_bid(bid)], {"bounty_id": bid.hex()})


def version() -> ContractCall:
    return ContractCall("version", lambda: [], {})


# --- Decoding -------------------------------------------------------------------------------------


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
    # v2 fields. A v1 escrow reads as one arbiter with threshold 1, no review window and no milestones.
    arbiters: tuple[str, ...] = ()
    threshold: int = 1
    review_window: int = 0
    pending_reviews: int = 0
    dispute_round: int = 0
    clock_reset_at: int = 0
    milestones: tuple[tuple[int, bool], ...] = ()  # (amount, paid) per milestone

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @property
    def arbiter_set(self) -> tuple[str, ...]:
        return self.arbiters or (self.arbiter,)

    def position_value(self) -> int:
        """Open value of one position: the reward, or the unpaid milestones of a milestone escrow."""
        if not self.milestones:
            return self.reward_per_position
        return sum(amount for amount, paid in self.milestones if not paid)

    def claimable_at(self, review_claimable_at: int) -> int:
        """When a review's claim opens: a dispute resolved later gives the requester a full window again."""
        if not self.clock_reset_at:
            return review_claimable_at
        return max(review_claimable_at, self.clock_reset_at + self.review_window)


@dataclass(frozen=True)
class ReviewSnapshot:
    """Decoded on-chain ``Review`` (a recorded submission and its clock)."""

    milestone: int
    submitted_at: int
    claimable_at: int
    state: str  # Pending | ChangesRequested | Rejected


@dataclass(frozen=True)
class VoteSnapshot:
    """A current-round arbiter approval (``resolution_votes``)."""

    arbiter: str
    contributor: str
    contributor_amount: int


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


def _milestones(value: Any) -> tuple[tuple[int, bool], ...]:
    return tuple((int(m["amount"]), bool(m["paid"])) for m in value or [])


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
        arbiters=tuple(_addr(a) for a in native.get("arbiters") or [native["arbiter"]]),
        threshold=int(native.get("threshold", 1)),
        review_window=int(native.get("review_window", 0)),
        pending_reviews=int(native.get("pending_reviews", 0)),
        dispute_round=int(native.get("dispute_round", 0)),
        clock_reset_at=int(native.get("clock_reset_at", 0)),
        milestones=_milestones(native.get("milestones")),
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


def _review_state(value: Any) -> str:
    if isinstance(value, int):
        return REVIEW_STATES[value]
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value)


def decode_review(native: Any) -> ReviewSnapshot | None:
    """``Option<Review>``."""
    if not isinstance(native, dict):
        return None
    return ReviewSnapshot(
        milestone=int(native["milestone"]),
        submitted_at=int(native["submitted_at"]),
        claimable_at=int(native["claimable_at"]),
        state=_review_state(native["state"]),
    )


def decode_votes(native: Any) -> list[VoteSnapshot]:
    return [
        VoteSnapshot(
            arbiter=_addr(v["arbiter"]),
            contributor=_addr(v["contributor"]),
            contributor_amount=int(v["contributor_amount"]),
        )
        for v in native or []
    ]


class ContractError(Exception):
    def __init__(self, code: int | None, message: str, raw: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.name = CONTRACT_ERRORS.get(code, ("Unknown", ""))[0] if code else "Unknown"
        self.message = message
        self.raw = raw


_TRUSTLINE_MESSAGE = "The receiving wallet has no trustline for this asset, so it cannot receive it."
_BALANCE_MESSAGE = "The wallet's balance of this asset is too low for this transaction."


def parse_contract_error(raw: str) -> ContractError:
    match = _CONTRACT_ERROR_RE.search(raw or "")
    lowered = (raw or "").lower()
    if match:
        code = int(match.group(1))
        _name, message = CONTRACT_ERRORS.get(code, ("Unknown", f"Contract error #{code}."))
        # SAC (token) errors also surface as Error(Contract, #n) but from the token contract: #13 is its
        # TrustlineMissingError (the escrow's own #13 is DeadlineInPast), #10 its BalanceError.
        if "trustline" in lowered:
            return ContractError(None, _TRUSTLINE_MESSAGE, raw)
        if "balance" in lowered and code not in (11,):
            return ContractError(code, _BALANCE_MESSAGE, raw)
        return ContractError(code, message, raw)
    if "trustline" in lowered:
        return ContractError(None, _TRUSTLINE_MESSAGE, raw)
    if "balance" in lowered or "underfunded" in lowered:
        return ContractError(None, _BALANCE_MESSAGE, raw)
    return ContractError(None, "The contract rejected this transaction during simulation.", raw)
