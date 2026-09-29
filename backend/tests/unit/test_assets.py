"""Pure asset helpers: identifiers and SAC ids, Horizon account parsing and reserves, trustline states, funding
problems, per-asset totals, contract error mapping, and per-asset daily metrics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.blockchain.assets import (
    NATIVE,
    InvalidAsset,
    is_contract_address,
    make_ref,
    native_contract_id,
    parse_identifier,
    sac_contract_id,
)
from app.blockchain.horizon import AccountState, AssetBalance, describe_codes, parse_account
from app.blockchain.soroban import parse_contract_error
from app.core.config import TESTNET_PASSPHRASE
from app.core.money import display_amount, display_xlm
from app.core.schemas import asset_amounts
from app.modules.analytics.service import build_daily_point
from app.modules.assets.checks import (
    _RECEIVING_TX_TYPES,
    funding_problem,
    receive_message,
    state_from_account,
)
from app.modules.assets.schemas import TrustlineState
from app.modules.payments.models import TxType

ISSUER = "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"
USDC = f"USDC:{ISSUER}"
HOLDER = "GDKMJJGPM7ZFTDG6Y74O6JA2QCMQBEJJE7Q7I5FGKI77Z67XXY2C3LU2"


def test_identifiers_and_contract_ids() -> None:
    assert parse_identifier(None).is_native and parse_identifier(NATIVE).code == "XLM"
    usdc = parse_identifier(USDC)
    assert (usdc.code, usdc.issuer, usdc.type) == ("USDC", ISSUER, "credit_alphanum4")
    assert make_ref("LONGERCODE12", ISSUER).type == "credit_alphanum12"
    assert (
        sac_contract_id(USDC, TESTNET_PASSPHRASE)
        == "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA"
    )
    assert (
        native_contract_id(TESTNET_PASSPHRASE) == "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC"
    )
    assert is_contract_address("CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA")
    assert not is_contract_address(HOLDER)
    for bad in ("USDC", "US$C:" + ISSUER, "USDC:GNOTANACCOUNT", "THIRTEENCHARS:" + ISSUER):
        with pytest.raises(InvalidAsset):
            parse_identifier(bad)
    with pytest.raises(InvalidAsset):
        make_ref("USDC", None)


def test_horizon_account_parsing_and_spendable_xlm() -> None:
    account = parse_account(
        {
            "account_id": HOLDER,
            "sequence": "123",
            "subentry_count": 2,
            "balances": [
                {"asset_type": "native", "balance": "10.0000000", "selling_liabilities": "1.0000000"},
                {
                    "asset_type": "credit_alphanum4",
                    "asset_code": "USDC",
                    "asset_issuer": ISSUER,
                    "balance": "25.5000000",
                    "limit": "922337203685.4775807",
                    "selling_liabilities": "5.5000000",
                    "is_authorized": True,
                },
                {"asset_type": "liquidity_pool_shares", "balance": "3"},
            ],
            "flags": {"auth_required": False, "auth_revocable": True},
        }
    )
    assert account.sequence == 123 and set(account.balances) == {NATIVE, USDC}
    assert account.minimum_balance == Decimal("2.0")  # (2 + 2 subentries) x 0.5 XLM
    assert account.native_spendable == Decimal("7")  # 10 - 2 reserve - 1 in offers
    usdc = account.balance(USDC)
    assert usdc is not None and usdc.spendable == Decimal("20")
    assert account.flags == {"auth_required": False, "auth_revocable": True}


def test_trustline_states() -> None:
    def acct(**balances: AssetBalance) -> AccountState:
        return AccountState(HOLDER, 1, {NATIVE: AssetBalance(NATIVE, Decimal(5)), **balances})

    assert state_from_account(None, USDC) == (TrustlineState.ACCOUNT_MISSING, None)
    assert state_from_account(acct(), USDC) == (TrustlineState.MISSING, None)
    active = acct(**{USDC: AssetBalance(USDC, Decimal("3"))})
    assert state_from_account(active, USDC) == (TrustlineState.ACTIVE, Decimal("3"))
    frozen = acct(**{USDC: AssetBalance(USDC, Decimal("3"), is_authorized=False)})
    assert state_from_account(frozen, USDC)[0] == TrustlineState.UNAUTHORIZED
    issuer = AccountState(ISSUER, 1, {NATIVE: AssetBalance(NATIVE, Decimal(5))})
    assert state_from_account(issuer, USDC)[0] == TrustlineState.NOT_REQUIRED
    assert state_from_account(acct(), NATIVE)[0] == TrustlineState.NOT_REQUIRED
    assert TrustlineState.UNKNOWN.can_receive and not TrustlineState.MISSING.can_receive


def test_funding_problems_are_specific() -> None:
    code, message = funding_problem(USDC, TrustlineState.MISSING, None, Decimal(10)) or ("", "")
    assert code == "trustline_missing" and "Add a USDC trustline" in message
    code, message = funding_problem(USDC, TrustlineState.ACTIVE, Decimal("4.5"), Decimal(10)) or ("", "")
    assert code == "insufficient_balance"
    assert message == "This wallet has 4.5 USDC available, less than the 10 USDC this deposit needs."
    assert funding_problem(USDC, TrustlineState.ACTIVE, Decimal(10), Decimal(10)) is None
    assert funding_problem(NATIVE, TrustlineState.UNKNOWN, None, Decimal(10)) is None
    assert funding_problem(USDC, TrustlineState.ACCOUNT_MISSING, None, Decimal(1))[0] == "account_not_found"  # type: ignore[index]
    assert receive_message("Kai Tanaka", "USDC", TrustlineState.MISSING) == (
        "Kai Tanaka's wallet can't receive USDC yet. They need to add a USDC trustline."
    )


def test_amount_display_and_per_asset_totals() -> None:
    assert display_amount(Decimal("1250.5"), "USDC") == "1,250.5 USDC"
    assert display_xlm(Decimal("12")) == "12 XLM"
    rows = asset_amounts({USDC: Decimal("5"), None: Decimal("2"), NATIVE: Decimal("1"), "EURC:" + ISSUER: 0})
    assert [(r.asset.code, r.amount) for r in rows] == [("XLM", Decimal("3")), ("USDC", Decimal("5"))]


def test_horizon_result_codes_and_contract_errors() -> None:
    assert describe_codes("tx_failed", ["op_low_reserve"])[0] == "op_low_reserve"
    assert describe_codes("tx_bad_seq", [])[0] == "tx_bad_seq"
    assert describe_codes(None, ["op_weird"]) == ("op_weird", "The transaction failed (op_weird).")
    # The SAC's TrustlineMissingError is #13, the escrow's own #13 is DeadlineInPast: text decides.
    missing = parse_contract_error("HostError: Error(Contract, #13) trustline entry is missing for account")
    assert "trustline" in missing.message
    assert parse_contract_error("Error(Contract, #13)").name == "DeadlineInPast"
    assert "XLM" not in parse_contract_error("Error(Contract, #10) balance is not sufficient").message


def test_daily_points_keep_assets_apart() -> None:
    point = build_daily_point(
        date(2026, 9, 29),
        {
            "payout_volume": Decimal("12.5"),
            f"payout_volume:{USDC}": Decimal("40"),
            "registrations": Decimal(2),
        },
    )
    assert point.payout_volume == Decimal("12.5")
    assert point.payout_volume_by_asset == {NATIVE: Decimal("12.5"), USDC: Decimal("40")}
    assert point.model_dump(mode="json")["payout_volume_by_asset"][USDC] == "40.0000000"


def test_every_paying_action_is_trustline_checked() -> None:
    """A new way to pay a contributor must not skip the trustline guard: ``batch_release`` pays up to ten
    contributors atomically, so one missing trustline would fail the whole transaction on-chain."""
    for tx_type in (TxType.PAYOUT, TxType.MILESTONE_PAYOUT, TxType.CLAIM, TxType.ASSIGN):
        assert tx_type in _RECEIVING_TX_TYPES
    # Batch payouts and dispute payments are checked on their own paths (every leg / only when they pay).
    assert TxType.BATCH_PAYOUT not in _RECEIVING_TX_TYPES
    assert TxType.DISPUTE_VOTE not in _RECEIVING_TX_TYPES


def test_a_claim_addresses_the_contributor_directly() -> None:
    assert receive_message("Kai Tanaka", "USDC", TrustlineState.MISSING, self_service=True) == (
        "Your wallet can't receive USDC yet. Add a USDC trustline, then claim."
    )
    assert receive_message("Kai Tanaka", "USDC", TrustlineState.NO_WALLET, self_service=True) == (
        "Verify a wallet before claiming USDC."
    )
