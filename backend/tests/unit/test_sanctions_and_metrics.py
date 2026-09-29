"""Sanctions list parsing, the metrics exposition format, and the chain-vs-database escrow diff."""

from __future__ import annotations

from decimal import Decimal

from stellar_sdk import Keypair

from app.blockchain.soroban import EscrowSnapshot
from app.modules.compliance.sanctions_list import parse
from app.modules.compliance.screening import _screenable, chain_addresses
from app.modules.ops.metrics import Counter, GaugeFamily, Histogram, render
from app.modules.ops.reconciliation_audit import diff
from app.modules.payments.models import BountyEscrow, EscrowState

A, B, C = (Keypair.random().public_key for _ in range(3))
# A passkey smart wallet address (the SEP-45 web-auth contract on Testnet stands in for one).
SMART_WALLET = "CB3GXQ2BW2AHSIWUITLVBKODKPUHIK5DLEPWIIWTKLTKLA6TE24PLSZX"


def test_ofac_sdn_remarks_yield_only_xlm_addresses() -> None:
    content = (
        f'123,"SOME EXCHANGE","-0-","Digital Currency Address - XBT 1BoatSLRHtKNngkdXEeobR76b53LETtpyT; '
        f'Digital Currency Address - XLM {A}; Digital Currency Address - ETH 0x12ab"\n'
        f'456,"OTHER","-0-","Digital Currency Address - XLM {B}."\n'
    )
    addresses, fmt = parse(content)
    assert fmt == "ofac-sdn" and addresses == {A, B}


def test_plain_and_json_lists() -> None:
    text = f"# comment line\n{A}   # the reason\n\nnot-an-address\n{B},extra,columns\n"
    assert parse(text) == ({A, B}, "text")
    assert parse(f'["{A}", {{"address": "{C}"}}, 42]') == ({A, C}, "json")


def test_addresses_with_a_bad_checksum_are_dropped() -> None:
    broken = A[:-1] + ("A" if A[-1] != "A" else "B")
    assert parse(f"{broken}\n{B}\n") == ({B}, "text")


def test_both_account_and_contract_addresses_are_screened() -> None:
    """A passkey smart wallet is a contract account that receives money like an account id does."""
    assert _screenable([A, SMART_WALLET, None, "", A]) == [A, SMART_WALLET]
    assert _screenable(["not-an-address", None]) == []


def test_every_leg_of_a_batch_payout_is_screened() -> None:
    """A batch settles atomically, so one sanctioned payee has to block the whole batch."""
    legs = [{"contributor": B, "amount": "5"}, {"contributor": SMART_WALLET, "amount": "3"}]
    assert chain_addresses(A, None, {"legs": legs}) == [A, None, B, SMART_WALLET]
    # A single payout still screens the signer and the one destination.
    assert chain_addresses(A, B, {}) == [A, B]
    assert chain_addresses(A, B, None) == [A, B]
    # Malformed metadata must never break a prepare; it simply adds no payees.
    assert chain_addresses(A, B, {"legs": "not-a-list"}) == [A, B]


def test_prometheus_text_format() -> None:
    counter = Counter("demo_total", "A counter.", ("route", "status"))
    counter.inc("/a/{id}", "200")
    counter.inc("/a/{id}", "200", amount=2)
    histogram = Histogram("demo_seconds", "A histogram.", ("route",), buckets=(0.1, 1.0))
    histogram.observe(0.05, "/a")
    histogram.observe(0.5, "/a")
    gauge = GaugeFamily("demo_gauge", 'Quotes " and \\ escaped.', ("name",)).set(1.5, 'x"y')
    text = render([counter, histogram, gauge])
    assert '# TYPE demo_total counter\ndemo_total{route="/a/{id}",status="200"} 3' in text
    assert 'demo_seconds_bucket{route="/a",le="0.1"} 1' in text
    assert 'demo_seconds_bucket{route="/a",le="1"} 2' in text
    assert 'demo_seconds_bucket{route="/a",le="+Inf"} 2' in text
    assert 'demo_seconds_count{route="/a"} 2' in text
    assert 'demo_gauge{name="x\\"y"} 1.5' in text
    assert text.endswith("\n")


def _escrow(**values: object) -> BountyEscrow:
    escrow = BountyEscrow(
        state=EscrowState.FUNDED,
        funded_amount=Decimal("5"),
        paid_out_amount=Decimal("0"),
        refunded_amount=Decimal("0"),
    )
    for key, value in values.items():
        setattr(escrow, key, value)
    return escrow


def _snapshot(**values: object) -> EscrowSnapshot:
    base: dict[str, object] = {
        "requester": A,
        "token": "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
        "arbiter": B,
        "reward_per_position": 50_000_000,
        "positions": 1,
        "required_amount": 50_000_000,
        "funded_amount": 50_000_000,
        "paid_out_amount": 0,
        "refunded_amount": 0,
        "payouts_made": 0,
        "assigned_unpaid": 0,
        "deadline": 2_000_000_000,
        "status": "Funded",
    }
    base.update(values)
    return EscrowSnapshot(**base)  # type: ignore[arg-type]


def test_escrow_diff() -> None:
    assert diff(_escrow(), _snapshot()) == {}
    assert diff(_escrow(funded_amount=Decimal("1")), _snapshot()) == {
        "funded_amount": ["1.0000000", "5.0000000"]
    }
    assert diff(_escrow(), _snapshot(status="Completed", paid_out_amount=50_000_000)) == {
        "state": ["FUNDED", "COMPLETED"],
        "paid_out_amount": ["0.0000000", "5.0000000"],
    }
    assert diff(_escrow(), None) == {"state": ["FUNDED", "missing on chain"]}
    assert diff(_escrow(state=EscrowState.NOT_CREATED), None) == {}
