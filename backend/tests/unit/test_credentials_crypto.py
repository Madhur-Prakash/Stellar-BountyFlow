"""Canonicalization, eddsa-jcs-2022 signatures, multibase keys and the Bitstring Status List.

Vectors: RFC 8785 (sections 3.2.2 and 3.2.3, appendix B) and the official W3C test vectors of the
eddsa-jcs-2022 cryptosuite (w3c/vc-di-eddsa, TestVectors/eddsa-jcs-2022).
"""

from __future__ import annotations

import copy
import hashlib
import json
import struct
from typing import Any

import pytest
from stellar_sdk import Keypair

from app.modules.credentials import data_integrity, status_list
from app.modules.credentials.issuer import address_from_subject, did_web, subject_did
from app.modules.credentials.jcs import CanonicalizationError, canonicalize
from app.modules.credentials.multibase import (
    b58decode,
    b58encode,
    decode_base58btc,
    ed25519_public_from_multikey,
    ed25519_public_multikey,
    ed25519_seed_from_multikey,
)

# --- RFC 8785 -----------------------------------------------------------------------------

NUMBER_SAMPLES = [
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
]


@pytest.mark.parametrize(("ieee", "expected"), NUMBER_SAMPLES)
def test_rfc8785_number_serialization(ieee: str, expected: str) -> None:
    value = struct.unpack(">d", bytes.fromhex(ieee))[0]
    assert canonicalize(value).decode() == expected


@pytest.mark.parametrize("ieee", ["7fffffffffffffff", "7ff0000000000000"])
def test_rfc8785_rejects_nan_and_infinity(ieee: str) -> None:
    with pytest.raises(CanonicalizationError):
        canonicalize(struct.unpack(">d", bytes.fromhex(ieee))[0])


def test_rfc8785_section_3_2_2_sample() -> None:
    source = r"""{
      "numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],
      "string": "\u20ac$\u000F\u000aA'\u0042\u0022\u005c\\\"\/",
      "literals": [null, true, false]
    }"""
    # The UTF-8 bytes given in RFC 8785 section 3.2.4.
    expected = bytes.fromhex(
        "7b226c69746572616c73223a5b6e756c6c2c74727565 2c66616c73655d2c226e756d62657273223a"
        "5b3333333333333333332e333333333333332c3165 2b33302c342e352c302e3030322c31652d3237"
        "5d2c22737472696e67223a22e282ac245c7530303066 5c6e4127425c225c5c5c5c5c222f227d".replace(" ", "")
    )
    assert canonicalize(json.loads(source)) == expected


def test_rfc8785_sorts_by_utf16_code_units() -> None:
    source = json.loads(
        r'{"€": "Euro Sign", "\r": "Carriage Return", "דּ": "Hebrew Letter Dalet With Dagesh",'
        r' "1": "One", "😀": "Emoji: Grinning Face", "\u0080": "Control",'
        r' "ö": "Latin Small Letter O With Diaeresis"}'
    )
    order = list(json.loads(canonicalize(source)).values())
    assert order == [
        "Carriage Return",
        "One",
        "Control",
        "Latin Small Letter O With Diaeresis",
        "Euro Sign",
        "Emoji: Grinning Face",
        "Hebrew Letter Dalet With Dagesh",
    ]


def test_canonicalization_is_recursive_and_keeps_array_order() -> None:
    assert canonicalize({"b": [{"z": 1, "a": 2}, 3], "a": {"d": True, "c": None}}) == (
        b'{"a":{"c":null,"d":true},"b":[{"a":2,"z":1},3]}'
    )


def test_canonicalization_rejects_non_json_values() -> None:
    with pytest.raises(CanonicalizationError):
        canonicalize({"lone": "\ud800"})
    with pytest.raises(CanonicalizationError):
        canonicalize({1: "number key"})
    with pytest.raises(CanonicalizationError):
        canonicalize({"when": object()})


# --- eddsa-jcs-2022 (official test vectors) ---------------------------------------------------

PUBLIC_KEY = "z6MkrJVnaZkeFzdQyMZu1cgjg7k1pZZ6pvBQ7XJPt4swbTQ2"
SECRET_KEY = "z3u2en7t5LR2WtQH5PfFqMqwVHBeXouLzo6haApm8XHqvjxq"
METHOD = f"did:key:{PUBLIC_KEY}#{PUBLIC_KEY}"
CONTEXT = ["https://www.w3.org/ns/credentials/v2", "https://www.w3.org/ns/credentials/examples/v2"]
UNSIGNED: dict[str, Any] = {
    "@context": CONTEXT,
    "id": "urn:uuid:58172aac-d8ba-11ed-83dd-0b3aef56cc33",
    "type": ["VerifiableCredential", "AlumniCredential"],
    "name": "Alumni Credential",
    "description": "A minimum viable example of an Alumni Credential.",
    "issuer": "https://vc.example/issuers/5678",
    "validFrom": "2023-01-01T00:00:00Z",
    "credentialSubject": {"id": "did:example:abcdefgh", "alumniOf": "The School of Examples"},
}
CANON_DOC = (
    '{"@context":["https://www.w3.org/ns/credentials/v2","https://www.w3.org/ns/credentials/examples/v2"],'
    '"credentialSubject":{"alumniOf":"The School of Examples","id":"did:example:abcdefgh"},'
    '"description":"A minimum viable example of an Alumni Credential.",'
    '"id":"urn:uuid:58172aac-d8ba-11ed-83dd-0b3aef56cc33","issuer":"https://vc.example/issuers/5678",'
    '"name":"Alumni Credential","type":["VerifiableCredential","AlumniCredential"],'
    '"validFrom":"2023-01-01T00:00:00Z"}'
)
DOC_HASH = "59b7cb6251b8991add1ce0bc83107e3db9dbbab5bd2c28f687db1a03abc92f19"
CANON_PROOF = (
    '{"@context":["https://www.w3.org/ns/credentials/v2","https://www.w3.org/ns/credentials/examples/v2"],'
    '"created":"2023-02-24T23:36:38Z","cryptosuite":"eddsa-jcs-2022","proofPurpose":"assertionMethod",'
    '"type":"DataIntegrityProof","verificationMethod":"' + METHOD + '"}'
)
PROOF_HASH = "66ab154f5c2890a140cb8388a22a160454f80575f6eae09e5a097cabe539a1db"
SIGNATURE_HEX = (
    "407cd12654b33d718ecbb99179a1506daaa849450bf3fc523cce3e1c96f8b803"
    "51da3f253d725c6f00b07c9e5448d50b3ef78012b9ab54255116d069c6dd2808"
)
PROOF_VALUE = "z2HnFSSPPBzR36zdDgK8PbEHeXbR56YF24jwMpt3R1eHXQzJDMWS93FCzpvJpwTWd3GAVFuUfjoJdcnTMuVor51aX"
CREATED = "2023-02-24T23:36:38Z"


def _signed() -> dict[str, Any]:
    return {
        **copy.deepcopy(UNSIGNED),
        "proof": {
            "type": "DataIntegrityProof",
            "cryptosuite": "eddsa-jcs-2022",
            "created": CREATED,
            "verificationMethod": METHOD,
            "proofPurpose": "assertionMethod",
            "@context": CONTEXT,
            "proofValue": PROOF_VALUE,
        },
    }


def _public() -> bytes:
    return ed25519_public_from_multikey(PUBLIC_KEY)


def test_vector_key_pair_is_consistent() -> None:
    seed = ed25519_seed_from_multikey(SECRET_KEY)
    assert Keypair.from_raw_ed25519_seed(seed).raw_public_key() == _public()
    assert ed25519_public_multikey(_public()) == PUBLIC_KEY


def test_vector_canonical_document_and_hashes() -> None:
    assert canonicalize(UNSIGNED).decode() == CANON_DOC
    assert hashlib.sha256(canonicalize(UNSIGNED)).hexdigest() == DOC_HASH
    config = data_integrity.proof_config(UNSIGNED, verification_method=METHOD, created=CREATED)
    assert canonicalize(config).decode() == CANON_PROOF
    assert hashlib.sha256(canonicalize(config)).hexdigest() == PROOF_HASH
    assert data_integrity.hash_data(UNSIGNED, config).hex() == PROOF_HASH + DOC_HASH


def test_vector_signature_and_proof_value() -> None:
    proof = data_integrity.create_proof(
        UNSIGNED, seed=ed25519_seed_from_multikey(SECRET_KEY), verification_method=METHOD, created=CREATED
    )
    assert decode_base58btc(proof["proofValue"]).hex() == SIGNATURE_HEX
    assert proof["proofValue"] == PROOF_VALUE
    assert proof == _signed()["proof"]


def test_vector_signed_credential_verifies() -> None:
    info = data_integrity.verify_proof(_signed(), _public())
    assert info.verification_method == METHOD and info.proof_purpose == "assertionMethod"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda d: d["credentialSubject"].__setitem__("alumniOf", "Another School"),
        lambda d: d.__setitem__("validFrom", "2023-01-02T00:00:00Z"),
        lambda d: d["type"].append("DiplomaCredential"),
        lambda d: d.__setitem__("extra", 1),
        lambda d: d["proof"].__setitem__("created", "2024-02-24T23:36:38Z"),
        lambda d: d["proof"].__setitem__("verificationMethod", METHOD + "x"),
        lambda d: d["proof"].__setitem__("proofValue", PROOF_VALUE[:-1] + "Y"),
        lambda d: d.__setitem__("@context", ["https://www.w3.org/ns/credentials/v2"]),
    ],
)
def test_tampering_is_detected(tamper: Any) -> None:
    document = _signed()
    tamper(document)
    with pytest.raises(data_integrity.ProofError):
        data_integrity.verify_proof(document, _public())


def test_another_key_does_not_verify() -> None:
    with pytest.raises(data_integrity.ProofError):
        data_integrity.verify_proof(_signed(), Keypair.random().raw_public_key())


def test_other_suites_and_missing_proofs_are_refused() -> None:
    for broken in ({"type": "Ed25519Signature2020"}, {"cryptosuite": "eddsa-rdfc-2022"}):
        document = _signed()
        document["proof"].update(broken)
        with pytest.raises(data_integrity.ProofError):
            data_integrity.verify_proof(document, _public())
    with pytest.raises(data_integrity.ProofError):
        data_integrity.verify_proof(copy.deepcopy(UNSIGNED), _public())
    with pytest.raises(data_integrity.ProofError):
        data_integrity.verify_proof({**UNSIGNED, "proof": [_signed()["proof"]]}, _public())


def test_sign_and_verify_round_trip() -> None:
    keypair = Keypair.random()
    signed = data_integrity.sign(
        {"@context": CONTEXT[:1], "type": ["VerifiableCredential"], "amount": "12.5000000", "n": 12},
        seed=keypair.raw_secret_key(),
        verification_method="did:web:example.org#k",
        created="2026-09-29T00:00:00Z",
    )
    data_integrity.verify_proof(signed, keypair.raw_public_key())
    # Key order and whitespace do not matter to JCS.
    reordered = json.loads(json.dumps(dict(reversed(list(signed.items()))), indent=2))
    data_integrity.verify_proof(reordered, keypair.raw_public_key())


# --- Multibase, DIDs, status list ---------------------------------------------------------------


def test_base58btc_round_trip_keeps_leading_zeros() -> None:
    for data in (b"", b"\0", b"\0\0abc", bytes(range(40))):
        assert b58decode(b58encode(data)) == data
    assert b58encode(b"hello world") == "StV1DL6CwTryKyV"


def test_did_web_and_did_pkh() -> None:
    assert did_web("localhost:5194") == "did:web:localhost%3A5194"
    assert did_web("BountyFlow.example") == "did:web:bountyflow.example"
    address = Keypair.random().public_key
    assert subject_did(address, "testnet") == f"did:pkh:stellar:testnet:{address}"
    assert subject_did(address, "mainnet") == f"did:pkh:stellar:pubnet:{address}"
    assert address_from_subject(f"did:pkh:stellar:testnet:{address}") == ("testnet", address)
    assert address_from_subject("did:example:123") is None


def test_status_list_bits_are_msb_first_and_compressed() -> None:
    encoded = status_list.encode([0, 7, 8, 131_071])
    assert encoded.startswith("u")
    bits = status_list.decode(encoded)
    assert len(bits) == 16_384
    assert bits[0] == 0b1000_0001 and bits[1] == 0b1000_0000 and bits[-1] == 0b0000_0001
    for index in (0, 7, 8, 131_071):
        assert status_list.is_set(bits, index)
    assert not status_list.is_set(bits, 1)
    with pytest.raises(status_list.StatusListError):
        status_list.encode([131_072])


def test_status_list_spec_example_is_an_empty_list() -> None:
    # The encodedList of the Bitstring Status List v1.0 example credential.
    bits = status_list.decode("uH4sIAAAAAAAAA-3BMQEAAADCoPVPbQwfoAAAAAAAAAAAAAAAAAAAAIC3AYbSVKsAQAAA")
    assert len(bits) == 16_384 and not any(bits)
