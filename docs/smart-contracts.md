# Smart contracts

The escrow contract lives in [`contracts/bounty_escrow`](../contracts/bounty_escrow). Its full reference covers the
interface, storage schema, event schema, error codes, and build/test/deploy commands; see
[`contracts/README.md`](../contracts/README.md). This page summarises the design and how the backend uses it.

## Deployment (Stellar Testnet)

| Item | Value |
|---|---|
| Contract ID (v2, new escrows) | `CBCXG46FJPYBPWYZ24BWFVNJ6G2ILFAXHX2COETDNXYE6C5IJWAZ3M4C` |
| Contract ID (v1, existing escrows) | `CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY` |
| Native XLM (SAC) | `CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC` |
| Admin (upgrades only) | `GAXPFJGPZ2X2DLQWKLQKUAX55MBY7SRXHK2HGC2KAV5QHOP6QCSDD26R` |
| Arbiter set on Testnet | 2 of `GDKMJJGPM7ZFTDG6Y74O6JA2QCMQBEJJE7Q7I5FGKI77Z67XXY2C3LU2`, `GBC4ELFGZ4EO2A7Q33GKNZ2RJRCQ56CGV4MP4RHKPEE4AXNN6ESJCZMA`, `GCS2KVV474R2V4M2CY45SINSNO7FPMOCBUE7WGH7UWHPXCSRGV3HHG5U` |
| Minimum review window | 60 s on this Testnet deployment (tests); 86,400 s (1 day) anywhere else |
| SDK | soroban-sdk 28, Stellar CLI 27 |
| Record | `contracts/deployments/testnet.json` (tx hashes, wasm hash, v2 smoke tests, superseded deployments) |

Redeploy with `make contract-deploy-testnet`. Deployer, admin and arbiter keys live in the local Stellar CLI key
store, never in the repository.

## Versions and routing

v1 had no admin and no upgrade entry point, so v2 is a new contract rather than an upgrade. Each
`bounty_escrows` row stores the `contract_id` and `contract_version` of the contract its escrow lives on, and every
call for that escrow goes to that contract (`soroban.on_contract`). Escrows created before v2 keep working on v1
with the v1 feature set (whole-position payouts, one arbiter). New escrows are created on `SOROBAN_CONTRACT_ID`.
The backend reads `version()` from that contract and only uses the v2 interface when it answers `2`
(`app/modules/escrow/config.py`), so pointing `SOROBAN_CONTRACT_ID` at a v1 contract turns the v2 features off.

From v2 on the contract is upgradeable: `upgrade(new_wasm_hash)` keeps the contract id and all escrows. Only the
admin set at deployment can call it, and every upgrade emits `contract_upgraded`.

## Model

- One escrow per bounty, keyed by `BytesN<32>` = `sha256("bountyflow:bounty:" || bounty_uuid || random_salt)`.
  The id is random (so nobody can pre-create a bounty's escrow) and stored in `bounty_escrows.onchain_bounty_id`.
  The backend only trusts an on-chain escrow whose terms match a creation it prepared (see
  [security.md](security.md)).
- `reward_per_position × positions = required_amount`. Funding may be partial (a creation with an initial deposit,
  then `fund`). The escrow becomes `Funded` only when fully funded.
- Native XLM moves through the **Stellar Asset Contract** using the standard token interface. Any SAC-compatible
  token works the same way; classic assets need a trustline on the recipient.
- `assign` locks a contributor on-chain. After that, the requester can refund only if the contributor consents
  (`consent_cancel`) or the deadline has passed.
- **Milestones.** A single-position escrow can split its reward into up to 20 milestones that add up to it. The
  escrow is funded once; `release_milestone` pays one milestone, and the last one completes the position.
- **Batch payouts.** `batch_release` pays up to 10 positions or milestones in one transaction. Every leg is checked
  and booked before any funds move, so the call pays all legs or none.
- **Review window.** A contributor can record submitted work with `submit_work`. The requester then has the
  escrow's review window (7 days by default, 1 to 30 days) to pay, `request_changes` or `reject_submission`. When
  the window passes unanswered, the contributor calls `claim` and is paid directly. A dispute pauses claims, and a
  resolved dispute gives pending submissions a full window again.
- **Disputes.** Either party can `raise_dispute`, which freezes payouts, claims and refunds. Each escrow stores an
  arbiter set and a threshold (M of N). An arbiter approves a resolution with `vote_resolution`: pay the assigned
  contributor an amount up to their open position, the rest going back to the requester, or remove their
  assignment. It executes when M arbiters approved exactly the same resolution in the current dispute round.
  `resolve_dispute` (v1 arguments) is a vote for all or nothing; with one arbiter it executes at once, as in v1.
  **Arbiters can never send funds to themselves or to any address other than the contributor and the requester.**
- The admin can upgrade the code and hand over the admin role (both admins sign). It cannot touch escrow funds
  through the contract's interface.

## Trust assumptions (summary)

1. Requesters trust that an approved payout will be signed. The contract cannot force a requester to release
   funds, but a contributor who records the work on-chain is paid by `claim` when the requester stays silent, and
   a dispute covers the rest.
2. Contributors who aren't locked on-chain (`assign`) can lose their claim to a refund. The UI offers `ASSIGN`
   after accepting a contributor, and "Record on-chain" after submitting work.
3. The arbiter set is controlled by platform staff. It has bounded power (see above). A threshold of 2 or more
   means no single key decides a dispute; mainnet requires it (`app/core/mainnet.py`).
4. The admin key can replace the contract code, so it is the most sensitive key of a deployment. Keep it offline
   (hardware wallet or multisig account) and treat every `contract_upgraded` event as a release.
5. The backend mirrors contract state for UX and analytics, but the contract is authoritative. Money is shown as
   funded or paid only after the chain reads so, and reconciliation overwrites the DB view with chain state.

See `contracts/README.md` → *Trust assumptions and limitations* for the complete list.

## How the backend calls it

`app/blockchain/soroban.py` encodes each call. Argument order matches `lib.rs` exactly; `EscrowTerms` and
`PayoutItem` are encoded as Soroban structs and enums. `transactions.py` builds, simulates, prepares and submits the
call against the escrow's own contract id. `verification.py` checks signed envelopes and decodes results.
`reconciliation.py` maps the contract's `Escrow` struct (including the arbiter set, threshold, review window, dispute
round and milestones) onto `bounty_escrows` and `bounty_milestones`. Read-only calls (`get_escrow`, `assignment`,
`review`, `resolution_votes`, `version`) are made through simulation, and nothing is submitted for them.

The v2 actions (`MILESTONE_PAYOUT`, `BATCH_PAYOUT`, `SUBMIT_WORK`, `REQUEST_CHANGES`, `REJECT_SUBMISSION`, `CLAIM`,
`DISPUTE_VOTE`) go through the same prepare → sign → submit → verify pipeline as the v1 ones
(`app/modules/escrow/chain.py` plans and settles them). A payment is marked confirmed only after the contract reads
it as paid; for a batch, every leg must read paid before any of them is confirmed.

# Attestation registry

A second, independent contract records completions: [`contracts/attestations`](../contracts/attestations). It
holds no funds and never touches the escrow. The escrow decides who gets paid; this registry is the public,
permanent record that they *were* paid.

## Deployment (Stellar Testnet)

| Item | Value |
|---|---|
| Contract id | `CBXJVFUQHWECJZQSEBAFGHXLHP72PCPUX7XES42KVEMVAMZ26D5CZ33N` |
| Attester | `GA4HHOAIAJKAOF5T33ZH5IQCWY7GPPI5S3KORSJYBULMEOOYZLUWW3CK` (secret in the root `.env`) |
| Wasm hash | `9fd157a8edf80d041759e23f916c1e410df779b1371a05186f5327f4ebe53ccd` |
| SDK | soroban-sdk 28 · Stellar CLI 27 |
| Record | `contracts/deployments/attestations-testnet.json` |

Redeploy with `scripts/deploy-attestations.ps1` (or `.sh`). The script generates the attester key into `.env` if
it is missing, funds it with Friendbot, deploys with that key as the constructor argument and writes
`ATTESTATION_CONTRACT_ID` back into `.env`. The attester secret never leaves `.env`.

## Model

- One attestation per **completion**: a `(bounty, contributor)` pair whose work is fully paid. Escrow v2 pays in
  several ways — one release, several milestone payouts, one leg of a batch payout, a claim after the review
  window, or a paying dispute resolution — so the attested amount is the *sum* of that contributor's confirmed
  payments on the bounty, in the bounty's reward asset. One batch transaction therefore produces several
  attestations, one per contributor it paid.
- The natural key is `(bounty_id, contributor, payout_tx)`, so a retried submission can never record the same
  completion twice (`AlreadyAttested`). `bounty_id` is the escrow's `BytesN<32>` key, and `payout_tx` is the hash
  of the transaction that completed the position.
- `contributor` is an `Address`: a classic account (`G…`) or a passkey smart-wallet contract (`C…`).
- Only the attester can `attest`, `revoke` (with a reason, 1–200 bytes) or hand the role to a new key
  (`set_attester`). Attestations are never deleted: a revoked one stays readable with its reason, and the
  contract refuses to attest that completion again.
- Reads: `get(id)`, `find(bounty_id, contributor, payout_tx)`, `list_by_contributor(contributor, start, limit)`
  (oldest first, at most 50 per call), `count_by_contributor`, `total`, `attester`, `version`.
- `extend_ttl(id)` is callable by anyone and extends every entry of one attestation. Records are persistent
  entries bumped to ~120 days on every write; archived entries are restorable, never deleted.

### Interface

| Function | Auth | Effect |
|---|---|---|
| `__constructor(attester)` | deployer | Sets the attester and an empty registry. |
| `attest(attester, contributor, bounty_id, escrow_contract, payout_tx, token, amount, completed_at)` | attester | Records a completion and returns it. Ids start at 1. `amount > 0` and `0 < completed_at <= now`; the attester cannot attest itself. |
| `revoke(attester, id, reason)` | attester | Marks the attestation revoked, keeping the reason and time. |
| `set_attester(attester, new_attester)` | attester | Rotates the role. Existing records keep the attester that wrote them. |
| `extend_ttl(id)` | none | Extends the record's storage entries. |

Errors: `NotFound` 1, `AlreadyAttested` 2, `Unauthorized` 3, `InvalidAmount` 4, `InvalidTimestamp` 5,
`AlreadyRevoked` 6, `InvalidReason` 7, `InvalidContributor` 8, `Overflow` 9.

Events: `completion_attested` (topics: name, contributor, bounty_id), `attestation_revoked` (topics: name,
contributor), `attester_rotated`.

## How the backend uses it

`app/modules/reputation/chain.py` encodes the calls and decodes the records; `service.py` runs the pipeline. The
platform signs these transactions itself with `STELLAR_ATTESTER_SECRET` (no user wallet is involved), so every
attester transaction takes a Redis lock and waits for its outcome before releasing it — two submissions never race
on the attester's sequence number. A row is queued only after a payment event whose position reads `Paid`
on-chain, and it is marked CONFIRMED only after the registry's record is read back and matches the completion.
The `attestation-reconciliation` job re-reads confirmed records and flags drift; a mismatched or missing record
stops being shown as completed on-chain.
