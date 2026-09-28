"""Exact money handling. Stellar amounts have 7 decimal places; on-chain values are integer stroops.

Floats are never used for monetary values anywhere in BountyFlow.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation

STROOPS_PER_UNIT = 10_000_000
DECIMALS = 7
QUANTUM = Decimal("0.0000001")
MAX_AMOUNT = Decimal("100000000000")  # 1e11 XLM — far above total supply, guards overflow

ZERO = Decimal("0")


def parse_amount(value: str | int | Decimal) -> Decimal:
    """Parse and validate a positive amount with at most 7 fractional digits."""
    if isinstance(value, float):  # pragma: no cover - defensive
        raise ValueError("Floating point amounts are not accepted")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid amount") from exc
    if not amount.is_finite():
        raise ValueError("Invalid amount")
    if amount.as_tuple().exponent < -DECIMALS:  # type: ignore[operator]
        raise ValueError("Amounts support at most 7 decimal places")
    if amount <= ZERO:
        raise ValueError("Amount must be greater than zero")
    if amount > MAX_AMOUNT:
        raise ValueError("Amount is too large")
    return amount.quantize(QUANTUM)


def to_stroops(amount: Decimal) -> int:
    quantized = amount.quantize(QUANTUM, rounding=ROUND_DOWN)
    if quantized != amount:
        raise ValueError("Amount has more than 7 decimal places")
    return int(quantized * STROOPS_PER_UNIT)


def from_stroops(stroops: int) -> Decimal:
    return (Decimal(stroops) / STROOPS_PER_UNIT).quantize(QUANTUM)


def fmt(amount: Decimal | None) -> str:
    """Serialize an amount as a fixed 7-decimal string."""
    return f"{(amount or ZERO).quantize(QUANTUM):f}"


def display_xlm(amount: Decimal | None) -> str:
    """Human-facing amount for messages, e.g. "150 XLM" or "12.5 XLM" (API fields keep the fixed 7-dp form)."""
    text = fmt(amount)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    grouped = f"{int(whole):,}"
    return f"{grouped}.{frac} XLM" if frac else f"{grouped} XLM"
