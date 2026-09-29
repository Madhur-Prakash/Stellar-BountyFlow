"""Reward asset identifiers and their Stellar Asset Contract (SAC) addresses.

Every amount BountyFlow records carries an *asset identifier*: ``"native"`` for XLM, or ``"CODE:ISSUER"`` for a
classic Stellar asset (e.g. ``USDC:GBBD…LFLA5``). Escrows hold tokens through the asset's SAC, whose contract id is
derived deterministically from the asset and the network passphrase, so it never has to be configured or trusted
from a client. These helpers are pure (no I/O).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from stellar_sdk import Asset as StellarAsset
from stellar_sdk.strkey import StrKey

NATIVE = "native"
NATIVE_CODE = "XLM"
# Stellar Asset Contracts always use 7 decimals, the precision of classic Stellar amounts.
SAC_DECIMALS = 7

AssetType = Literal["native", "credit_alphanum4", "credit_alphanum12"]

_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,12}$")


class InvalidAsset(ValueError):
    """The asset code, issuer or identifier is malformed."""


@dataclass(frozen=True)
class AssetRef:
    """A parsed asset identifier."""

    code: str
    issuer: str | None

    @property
    def is_native(self) -> bool:
        return self.issuer is None

    @property
    def identifier(self) -> str:
        return NATIVE if self.issuer is None else f"{self.code}:{self.issuer}"

    @property
    def type(self) -> AssetType:
        if self.issuer is None:
            return "native"
        return "credit_alphanum4" if len(self.code) <= 4 else "credit_alphanum12"

    def to_stellar(self) -> StellarAsset:
        return StellarAsset.native() if self.issuer is None else StellarAsset(self.code, self.issuer)


def validate_code(code: str) -> str:
    code = (code or "").strip()
    if not _CODE_RE.fullmatch(code):
        raise InvalidAsset("An asset code is 1 to 12 letters or digits.")
    if code.upper() == NATIVE_CODE and code != NATIVE_CODE:
        raise InvalidAsset("XLM is the native asset and has no issuer.")
    return code


def validate_issuer(issuer: str) -> str:
    issuer = (issuer or "").strip()
    if not StrKey.is_valid_ed25519_public_key(issuer):
        raise InvalidAsset("The issuer must be a Stellar account address (G…).")
    return issuer


def make_ref(code: str, issuer: str | None) -> AssetRef:
    if issuer is None:
        if (code or "").strip().upper() not in (NATIVE_CODE, NATIVE.upper()):
            raise InvalidAsset("Only XLM has no issuer.")
        return AssetRef(NATIVE_CODE, None)
    return AssetRef(validate_code(code), validate_issuer(issuer))


def parse_identifier(identifier: str | None) -> AssetRef:
    """``"native"`` (or ``None``, which older rows use) → XLM; ``"CODE:ISSUER"`` → that classic asset."""
    if identifier is None or identifier == NATIVE:
        return AssetRef(NATIVE_CODE, None)
    code, sep, issuer = identifier.partition(":")
    if not sep:
        raise InvalidAsset(f"Unknown asset identifier {identifier!r}.")
    return AssetRef(validate_code(code), validate_issuer(issuer))


@lru_cache(maxsize=512)
def sac_contract_id(identifier: str, network_passphrase: str) -> str:
    """The contract id of the asset's Stellar Asset Contract on this network (deterministic)."""
    return parse_identifier(identifier).to_stellar().contract_id(network_passphrase)


def native_contract_id(network_passphrase: str) -> str:
    return sac_contract_id(NATIVE, network_passphrase)


def is_contract_address(address: str) -> bool:
    """C… addresses (smart wallets, contracts) hold SAC balances in contract storage and need no trustline."""
    return StrKey.is_valid_contract(address)
