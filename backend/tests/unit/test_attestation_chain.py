"""Encoding of attestation registry calls and decoding of its records and errors (contracts/attestations)."""

from __future__ import annotations

from stellar_sdk import Address, Keypair, scval
from stellar_sdk import xdr as stellar_xdr

from app.modules.reputation.chain import (
    Completion,
    attest_args,
    decode_attestation,
    parse_error,
    revoke_args,
)

CONTRIBUTOR = Keypair.random().public_key
ATTESTER = Keypair.random().public_key
ESCROW = "CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY"
TOKEN = "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC"
COMPLETION = Completion(
    contributor=CONTRIBUTOR,
    bounty_id=bytes(range(32)),
    escrow_contract=ESCROW,
    payout_tx=bytes.fromhex("ab" * 32),
    token=TOKEN,
    amount=125_000_000,
    completed_at=1_790_000_000,
)


def test_attest_arguments_follow_the_contract_signature() -> None:
    args = attest_args(ATTESTER, COMPLETION)
    types = [a.type for a in args]
    assert types == [
        stellar_xdr.SCValType.SCV_ADDRESS,
        stellar_xdr.SCValType.SCV_ADDRESS,
        stellar_xdr.SCValType.SCV_BYTES,
        stellar_xdr.SCValType.SCV_ADDRESS,
        stellar_xdr.SCValType.SCV_BYTES,
        stellar_xdr.SCValType.SCV_ADDRESS,
        stellar_xdr.SCValType.SCV_I128,
        stellar_xdr.SCValType.SCV_U64,
    ]
    native = [scval.to_native(a) for a in args]
    assert native[0].address == ATTESTER and native[1].address == CONTRIBUTOR
    assert native[2] == COMPLETION.bounty_id and native[4] == COMPLETION.payout_tx
    assert native[6] == 125_000_000 and native[7] == 1_790_000_000


def test_revoke_arguments() -> None:
    args = revoke_args(ATTESTER, 7, "Recorded by mistake")
    assert [a.type for a in args] == [
        stellar_xdr.SCValType.SCV_ADDRESS,
        stellar_xdr.SCValType.SCV_U64,
        stellar_xdr.SCValType.SCV_STRING,
    ]
    assert scval.to_native(args[2]) == "Recorded by mistake"


def test_decoded_record_matches_the_completion_it_states() -> None:
    record = decode_attestation(
        {
            "id": 3,
            "attester": Address(ATTESTER),
            "contributor": Address(CONTRIBUTOR),
            "bounty_id": COMPLETION.bounty_id,
            "escrow_contract": Address(ESCROW),
            "payout_tx": COMPLETION.payout_tx,
            "token": Address(TOKEN),
            "amount": 125_000_000,
            "completed_at": 1_790_000_000,
            "attested_at": 1_790_000_100,
            "contributor_index": 0,
            "revoked": False,
            "revoked_at": 0,
            "revocation_reason": b"",
        }
    )
    assert record.id == 3 and record.bounty_id == COMPLETION.bounty_id.hex()
    assert record.matches(COMPLETION)
    assert not record.matches(Completion(**{**COMPLETION.__dict__, "amount": 1}))
    assert not record.matches(Completion(**{**COMPLETION.__dict__, "payout_tx": bytes(32)}))
    assert record.revoked_datetime is None and record.attested_datetime.year == 2026


def test_contract_errors_are_named_and_classified() -> None:
    duplicate = parse_error("HostError: Error(Contract, #2)")
    assert duplicate.name == "AlreadyAttested" and not duplicate.permanent
    unauthorized = parse_error("Error(Contract, #3)")
    assert unauthorized.name == "Unauthorized" and unauthorized.permanent
    assert parse_error("Error(Contract, #6)").name == "AlreadyRevoked"
    assert parse_error("insufficient balance").code is None
