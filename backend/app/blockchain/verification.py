"""Independent verification of signed transactions and decoding of network results."""

from __future__ import annotations

from dataclasses import dataclass

from stellar_sdk import Keypair, TransactionEnvelope
from stellar_sdk import xdr as stellar_xdr
from stellar_sdk.exceptions import BadSignatureError

# Human-readable reasons for transaction-level result codes.
TX_RESULT_MESSAGES: dict[str, str] = {
    "txBAD_SEQ": "Sequence number conflict — another transaction from this account was submitted first. Please retry.",
    "txTOO_LATE": "The transaction expired before it was submitted. Please prepare it again.",
    "txTOO_EARLY": "The transaction is not valid yet.",
    "txINSUFFICIENT_BALANCE": "Insufficient XLM balance to pay the transaction fee and reserves.",
    "txINSUFFICIENT_FEE": "The network fee was too low. Please retry.",
    "txBAD_AUTH": "The transaction signature is invalid or missing.",
    "txBAD_AUTH_EXTRA": "The transaction has unexpected extra signatures.",
    "txNO_ACCOUNT": "The source account does not exist on this network. Fund it first (Friendbot on Testnet).",
    "txFAILED": "The transaction failed during execution.",
    "txSOROBAN_INVALID": "The Soroban transaction data is invalid. Please prepare it again.",
    "txMALFORMED": "The transaction is malformed.",
    "txINTERNAL_ERROR": "The network reported an internal error.",
}


class EnvelopeMismatch(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedEnvelope:
    hash_hex: str
    source: str
    xdr: str


def verify_signed_envelope(
    signed_xdr: str, *, expected_hash: str, expected_source: str, network_passphrase: str
) -> VerifiedEnvelope:
    """Ensures the wallet signed exactly the transaction we prepared (signatures do not change the hash),
    that its source account is the expected wallet, and that the source signature is cryptographically valid."""
    try:
        envelope = TransactionEnvelope.from_xdr(signed_xdr, network_passphrase)
    except Exception as exc:
        raise EnvelopeMismatch("The signed transaction could not be decoded.") from exc
    tx_hash = envelope.hash_hex()
    if tx_hash != expected_hash:
        raise EnvelopeMismatch("The signed transaction does not match the prepared transaction.")
    source = envelope.transaction.source.account_id
    if source != expected_source:
        raise EnvelopeMismatch("The transaction source account does not match your verified wallet.")
    if not envelope.signatures:
        raise EnvelopeMismatch("The transaction has not been signed.")
    keypair = Keypair.from_public_key(source)
    tx_hash_bytes = envelope.hash()
    for signature in envelope.signatures:
        if signature.signature_hint != keypair.signature_hint():
            continue
        try:
            keypair.verify(tx_hash_bytes, signature.signature)
            return VerifiedEnvelope(hash_hex=tx_hash, source=source, xdr=signed_xdr)
        except BadSignatureError:
            continue
    raise EnvelopeMismatch("No valid signature from the source wallet was found.")


def decode_tx_result_code(result_xdr: str | None) -> str | None:
    if not result_xdr:
        return None
    try:
        result = stellar_xdr.TransactionResult.from_xdr(result_xdr)
        return result.result.code.name  # e.g. "txFAILED"
    except Exception:
        return None


def describe_result_code(code: str | None) -> str:
    if not code:
        return "The transaction failed."
    return TX_RESULT_MESSAGES.get(code, f"The transaction failed ({code}).")


def extract_return_value(result_meta_xdr: str | None) -> stellar_xdr.SCVal | None:
    """Pulls the Soroban invocation return value from TransactionMeta (v3 or v4)."""
    if not result_meta_xdr:
        return None
    try:
        meta = stellar_xdr.TransactionMeta.from_xdr(result_meta_xdr)
    except Exception:
        return None
    for attr in ("v4", "v3"):
        body = getattr(meta, attr, None)
        soroban_meta = getattr(body, "soroban_meta", None) if body is not None else None
        if soroban_meta is not None and getattr(soroban_meta, "return_value", None) is not None:
            return soroban_meta.return_value
    return None
