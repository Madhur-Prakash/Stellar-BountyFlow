# Verifiable credentials

A contributor whose completion is attested on-chain can download a **W3C Verifiable Credential 2.0** for it and
show it anywhere. Anyone can check one at `/credentials/verify` without an account: the page reports the
signature, the issuer, the validity period, the revocation status and a live read of the on-chain attestation.

- [Format](#format)
- [Issuer](#issuer-didweb)
- [Subject](#subject-didpkh)
- [What a credential says](#what-a-credential-says)
- [Revocation](#revocation-bitstring-status-list)
- [Verification](#verification)
- [Configuration](#configuration)
- [Test vectors](#test-vectors)

## Format

Data Integrity proofs with the **`eddsa-jcs-2022`** cryptosuite (VC Data Integrity EdDSA Cryptosuites v1.0).

Why this and not VC-JOSE (an EdDSA JWT), and not `eddsa-rdfc-2022`:

- **No network at verification time.** JCS (RFC 8785) canonicalizes the JSON as it stands. RDFC would require
  JSON-LD expansion, which fetches `@context` documents — a verifier that cannot reach the network, or that is
  served a different context, gets a different answer. Signing and verifying here are pure functions of the
  document's bytes.
- **The credential stays readable JSON.** A JWT hides the claims inside a base64 blob; our credential can be
  pasted into the verify page, read by a person, and diffed against what the site shows. Tampering is still
  detected, because the proof covers the canonical form of every field.
- **One key type end to end.** Ed25519 is what Stellar already uses, so the issuer key is an ordinary Stellar
  secret seed and the same primitives sign the proof.

The trade-off: `eddsa-jcs-2022` is not a JSON-LD-secured credential, so a consumer doing full JSON-LD processing
must fetch the contexts itself. Our credentials use only the VC 2.0 base context and plain JSON claims.

## Issuer: `did:web`

The issuer is the site itself, as `did:web:<host>` (a port is percent-encoded, e.g.
`did:web:localhost%3A5194`). Its DID document is served by the API at **`/.well-known/did.json`**, and the
frontend's nginx and the Vite dev server proxy that path to the API, so it is reachable at the site's own origin —
which is what makes `did:web` resolvable.

```json
{
  "@context": ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/multikey/v1"],
  "id": "did:web:bountyflow.example",
  "verificationMethod": [
    {
      "id": "did:web:bountyflow.example#z6Mk…",
      "type": "Multikey",
      "controller": "did:web:bountyflow.example",
      "publicKeyMultibase": "z6Mk…"
    }
  ],
  "assertionMethod": ["did:web:bountyflow.example#z6Mk…"],
  "service": [{ "id": "…#site", "type": "LinkedDomains", "serviceEndpoint": "https://bountyflow.example" }]
}
```

The key is an Ed25519 Multikey (`z6Mk…`, multicodec `0xed01`). It comes only from `CREDENTIAL_ISSUER_SECRET`; with
no key the whole feature is off and says so in the UI and at `GET /credentials/issuer`.

Rotating the key changes the verification method id. Credentials signed with the previous key no longer verify
here, so a re-issue supersedes (revokes) the old one automatically.

## Subject: `did:pkh`

The subject is the **account that received the money**: `did:pkh:stellar:<reference>:<address>`, where the
reference is the CAIP-2 one for the network (`testnet`, or `pubnet` for mainnet) and the address is the exact
strkey BountyFlow paid.

That address is a classic account (`G…`) for an ordinary wallet and a **contract address (`C…`) for a passkey
smart wallet**. Both are valid Stellar account addresses in CAIP-10 terms, so both are used as-is; nothing about
the DID scheme changes. A verifier that wants to check control of the subject asks for a Stellar signature from a
`G…` address, or a smart-wallet authorization from a `C…` one — the same distinction Stellar itself makes.

A summary credential names the address of the most recent completion as its subject; each completion listed
inside it still carries the address that completion was paid to.

## What a credential says

Two kinds, both issued to the contributor on request:

**`BountyCompletionCredential`** — one attested completion.

```json
{
  "@context": ["https://www.w3.org/ns/credentials/v2"],
  "id": "urn:uuid:…",
  "type": ["VerifiableCredential", "BountyCompletionCredential"],
  "name": "Bounty completion",
  "description": "Completed “…” on BountyFlow and was paid 250 USDC from escrow on Stellar.",
  "issuer": { "id": "did:web:…", "name": "BountyFlow", "url": "https://…" },
  "validFrom": "2026-09-29T10:00:00Z",
  "credentialSubject": {
    "id": "did:pkh:stellar:testnet:G…",
    "name": "…", "username": "…", "profile": "https://…/u/…",
    "completion": {
      "type": "BountyCompletion",
      "bounty": { "id": "…", "title": "…", "url": "https://…/bounties/…" },
      "amount": "250.0000000",
      "asset": { "code": "USDC", "issuer": "GBBD…", "contract": "CBIE…" },
      "payments": [{ "amount": "100.0000000", "settledAt": "…", "transaction": "…", "kind": "MILESTONE_PAYOUT", "milestone": "Design" }],
      "completedAt": "…", "network": "stellar:testnet", "recipient": "G…",
      "payoutTransaction": "…", "escrowContract": "C…", "escrowBountyId": "…",
      "attestation": { "contract": "C…", "id": 7, "transaction": "…", "attestedAt": "…", "url": "https://…/attestations/7" }
    }
  },
  "credentialStatus": { "type": "BitstringStatusListEntry", "statusPurpose": "revocation", "statusListIndex": "…", "statusListCredential": "https://…/api/v1/credentials/status/revocation" },
  "proof": { "type": "DataIntegrityProof", "cryptosuite": "eddsa-jcs-2022", "created": "…", "verificationMethod": "did:web:…#z6Mk…", "proofPurpose": "assertionMethod", "proofValue": "z…" }
}
```

`amount` is everything the contributor was paid on that bounty, in the bounty's asset; `payments` lists the
transfers behind it (a single release, the milestones, or the batch leg). Amounts of different assets are never
added together — a summary reports one total per asset.

**`ContributorReputationCredential`** — every standing attested completion at issue time: the count, the totals
per asset, the first and last completion dates, and each attestation's id, bounty, recipient, amount, asset,
payout transaction and escrow. It covers at most 100 completions.

Issuing is idempotent: asking again returns the standing credential unless the set of completions changed or the
issuer key rotated.

## Revocation: Bitstring Status List

Each credential carries a `BitstringStatusListEntry` pointing at
`GET /api/v1/credentials/status/revocation`, a signed `BitstringStatusListCredential` (131,072 entries, GZIP,
multibase `u…`). Indexes are allocated at random, so a credential's position reveals nothing about when it was
issued.

A bit is set when:

- the on-chain attestation behind the credential is revoked (the pipeline revokes every credential stating it, in
  the same transaction that records the revocation), or
- the credential was superseded by a re-issue after a key rotation.

The status list credential is rebuilt at most every 30 seconds and signed with the same issuer key.

## Verification

`POST /api/v1/credentials/verify` takes `{ "credential": … }` and answers with a report: six checks, each
`pass`, `fail` or `skip`, plus the issuer, the subject and every attestation it read. The route is public and
CSRF-exempt — it reads only.

| Check | What it means |
|---|---|
| `format` | A VC 2.0 document: the base context first, `VerifiableCredential` in `type`, an issuer, a subject and a proof. |
| `issuer` | The issuer is this site's `did:web`. Credentials from elsewhere are reported, not verified (the later checks are skipped). |
| `signature` | The `eddsa-jcs-2022` proof verifies against the issuer's current key, with `assertionMethod` as its purpose. |
| `validity` | `validFrom` has passed (5 minutes of clock skew allowed) and `validUntil`, if present, has not. |
| `status` | The credential is in the issuer's records and its status-list bit is not set. |
| `attestation` | Every attestation the credential states is read from the registry contract and compared field by field: recipient, escrow bounty id, payout transaction, escrow contract, token, amount and completion time. A revoked or mismatched record fails. |

Tampering with any field breaks the signature, because the proof covers the canonical form of the whole document;
changing the claims *and* the amount still fails the attestation check against the contract.

## Configuration

| Variable | Meaning |
|---|---|
| `CREDENTIAL_ISSUER_SECRET` | Ed25519 key (a Stellar secret seed) that signs credentials. Empty = the feature is off. |
| `CREDENTIAL_ISSUER_DOMAIN` | `did:web` host, port included. Defaults to the `FRONTEND_URL` host. |

Generate a key with `python -c "from stellar_sdk import Keypair; print(Keypair.random().secret)"`. It holds no
funds and signs nothing that is submitted to the network. Keep it in the root `.env` only.

## Endpoints

| Method | Path | Who |
|---|---|---|
| `GET` | `/.well-known/did.json` | public (unversioned) |
| `GET` | `/credentials/issuer` | public |
| `GET` | `/credentials/status/revocation` | public |
| `POST` | `/credentials/verify` | public, CSRF-exempt |
| `POST` | `/credentials/completions/{attestation_id}` | the contributor |
| `POST` | `/credentials/summary` | the contributor |
| `GET` | `/credentials/me` | the owner |
| `GET` | `/credentials/{id}` · `/credentials/{id}/download` | the owner |

## Test vectors

`backend/tests/unit/test_credentials_crypto.py` pins the implementation to published vectors:

- **RFC 8785** — the number-serialization table (Appendix B), the worked example of section 3.2.2 down to its
  UTF-8 bytes, and the UTF-16 property-sorting sample of section 3.2.3.
- **W3C `eddsa-jcs-2022`** (`w3c/vc-di-eddsa`, `TestVectors/eddsa-jcs-2022`) — the key pair, the canonical
  document and proof configuration, both SHA-256 hashes, the raw signature and its `z…` proof value, verified
  end to end.
- Tampering (eight mutations of a signed credential), a foreign key, other cryptosuites, and the Bitstring
  Status List example from the specification.
EOF
