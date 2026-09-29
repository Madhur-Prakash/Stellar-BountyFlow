"""JSON Canonicalization Scheme (RFC 8785), the canonical form ``eddsa-jcs-2022`` signs.

* Object members are sorted by their names as arrays of UTF-16 code units.
* Strings use the minimal JSON escaping of ECMAScript's ``JSON.stringify``.
* Numbers are IEEE 754 doubles serialized like ECMAScript's ``Number.prototype.toString``.
* No whitespace; the result is UTF-8.

Pure Python, no network access and no JSON-LD processing.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from typing import Any


class CanonicalizationError(ValueError):
    """The value cannot be canonicalized (NaN, Infinity, lone surrogates, non-JSON types)."""


def _number(value: int | float) -> str:
    try:
        number = float(value)
    except OverflowError as exc:
        raise CanonicalizationError("The number is outside the IEEE 754 double range") from exc
    if math.isnan(number) or math.isinf(number):
        raise CanonicalizationError("NaN and Infinity are not valid JSON numbers")
    if number == 0:
        return "0"  # also -0
    # repr() gives the shortest digit string that round-trips, which is what ECMAScript uses.
    _, digit_tuple, exponent = Decimal(repr(abs(number))).as_tuple()
    assert isinstance(exponent, int)
    digits = "".join(map(str, digit_tuple)).lstrip("0")
    stripped = digits.rstrip("0")
    exponent += len(digits) - len(stripped)
    digits = stripped
    k = len(digits)
    n = exponent + k  # the value is 0.<digits> x 10^n
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        text = "0." + "0" * (-n) + digits
    else:
        head = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        text = f"{head}e{'+' if n - 1 >= 0 else '-'}{abs(n - 1)}"
    return ("-" if number < 0 else "") + text


def _string(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("Strings must not contain lone surrogates") from exc
    return json.dumps(value, ensure_ascii=False)


def _sort_key(name: str) -> bytes:
    return name.encode("utf-16-be", "surrogatepass")


def _serialize(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int | float):
        out.append(_number(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, list | tuple):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _serialize(item, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise CanonicalizationError("Object member names must be strings")
        out.append("{")
        for index, key in enumerate(sorted(value, key=_sort_key)):
            if index:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _serialize(value[key], out)
        out.append("}")
    else:
        raise CanonicalizationError(f"{type(value).__name__} is not a JSON value")


def canonicalize(value: Any) -> bytes:
    """RFC 8785 canonical UTF-8 bytes of a JSON value (as parsed by ``json.loads``)."""
    out: list[str] = []
    _serialize(value, out)
    return "".join(out).encode("utf-8")
