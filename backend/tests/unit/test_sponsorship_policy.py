"""Fee-sponsorship policy and fee-bump construction, without a network or a database.

The policy decisions that need a session are covered in
``tests/integration/api/test_wallets_api.py``; this file covers the pure parts: which envelopes may be
sponsored, what a fee bump looks like, and that a fee bump reports the *inner* transaction's result.
"""

from __future__ import annotations

from typing import Any

import pytest
from stellar_sdk import Account, Asset, Keypair, Network, TransactionBuilder, TransactionEnvelope

from app.blockchain import sponsorship
from app.blockchain.transactions import envelope_hashes, is_contract_address
from app.blockchain.verification import decode_tx_result_code
from app.core.config import get_settings

PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
SPONSOR = Keypair.from_raw_ed25519_seed(bytes(range(32)))


@pytest.fixture(autouse=True)
def _sponsor(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.blockchain.config import get_network

    monkeypatch.setenv("STELLAR_NETWORK_PASSPHRASE", PASSPHRASE)
    monkeypatch.setenv("BLOCKCHAIN_MODE", "testnet")
    monkeypatch.setenv("STELLAR_NETWORK", "testnet")
    monkeypatch.setenv("STELLAR_SPONSOR_SECRET", SPONSOR.secret)
    get_settings.cache_clear()
    get_network.cache_clear()
    yield
    get_settings.cache_clear()
    get_network.cache_clear()


def _payment(source: Keypair, fee: int = 100) -> TransactionEnvelope:
    tx = (
        TransactionBuilder(Account(source.public_key, 4), PASSPHRASE, base_fee=fee)
        .append_payment_op(Keypair.random().public_key, Asset.native(), "1")
        .set_timeout(120)
        .build()
    )
    tx.sign(source)
    return tx


def test_sponsorship_is_off_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STELLAR_SPONSOR_SECRET", raising=False)
    get_settings.cache_clear()
    assert sponsorship.sponsor_keypair() is None
    assert sponsorship.is_enabled() is False


def test_the_sponsor_pays_and_the_inner_transaction_is_unchanged() -> None:
    user = Keypair.random()
    inner = _payment(user)
    xdr, bump_hash, max_fee = sponsorship.fee_bump(inner.to_xdr())

    assert sponsorship.is_fee_bump(xdr)
    sent, carried = envelope_hashes(xdr, PASSPHRASE)
    assert sent == bump_hash
    # The user's transaction — the hash BountyFlow tracks — is carried unchanged inside the bump.
    assert carried == inner.hash_hex()
    assert max_fee > inner.transaction.fee


def test_a_fee_bump_reports_the_users_transaction_result() -> None:
    """Horizon returns the outer result for a fee bump; only the inner result describes the user's call."""
    from stellar_sdk import xdr as stellar_xdr

    inner_result = stellar_xdr.TransactionResult(
        fee_charged=stellar_xdr.Int64(100),
        result=stellar_xdr.TransactionResultResult(
            code=stellar_xdr.TransactionResultCode.txFAILED,
            results=[],
        ),
        ext=stellar_xdr.TransactionResultExt(0),
    )
    outer = stellar_xdr.TransactionResult(
        fee_charged=stellar_xdr.Int64(200),
        result=stellar_xdr.TransactionResultResult(
            code=stellar_xdr.TransactionResultCode.txFEE_BUMP_INNER_FAILED,
            inner_result_pair=stellar_xdr.InnerTransactionResultPair(
                transaction_hash=stellar_xdr.Hash(bytes(32)),
                result=stellar_xdr.InnerTransactionResult(
                    fee_charged=stellar_xdr.Int64(100),
                    result=stellar_xdr.InnerTransactionResultResult(
                        code=stellar_xdr.TransactionResultCode.txFAILED, results=[]
                    ),
                    ext=stellar_xdr.InnerTransactionResultExt(0),
                ),
            ),
        ),
        ext=stellar_xdr.TransactionResultExt(0),
    )
    assert decode_tx_result_code(inner_result.to_xdr()) == "txFAILED"
    assert decode_tx_result_code(outer.to_xdr()) == "txFAILED"


def test_only_allowed_calls_and_trustlines_are_sponsorable() -> None:
    settings = get_settings()
    # The escrow actions a contributor takes, and nothing the requester does.
    assert "claim" in settings.sponsor_allowed_functions
    assert "submit_work" in settings.sponsor_allowed_functions
    assert "consent_cancel" in settings.sponsor_allowed_functions
    assert "raise_dispute" in settings.sponsor_allowed_functions
    for requester_side in ("release", "release_milestone", "batch_release", "refund", "create_escrow"):
        assert requester_side not in settings.sponsor_allowed_functions


def test_contract_addresses_are_recognised() -> None:
    assert is_contract_address("CBCXG46FJPYBPWYZ24BWFVNJ6G2ILFAXHX2COETDNXYE6C5IJWAZ3M4C") is True
    assert is_contract_address(Keypair.random().public_key) is False
    assert is_contract_address(None) is False


def test_refusals_have_a_message_for_every_reason() -> None:
    for reason in (
        "disabled",
        "contract",
        "function",
        "requester",
        "max_fee",
        "daily_tx",
        "daily_fee",
        "balance",
    ):
        message = sponsorship.refusal_message(reason)
        assert message and not message.endswith("eligible for fee sponsorship.")
    assert sponsorship.refusal_message(None).endswith("eligible for fee sponsorship.")
