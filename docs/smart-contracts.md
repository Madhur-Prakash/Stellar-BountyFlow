# Smart contracts

The escrow contract lives in [`contracts/bounty_escrow`](../contracts/bounty_escrow). Its full reference covers the
interface, storage schema, event schema, error codes, and build/test/deploy commands; see
[`contracts/README.md`](../contracts/README.md). This page summarises the design and how the backend uses it.

## Deployment (Stellar Testnet)

| Item | Value |
|---|---|
| Contract ID | `CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY` |
| Native XLM (SAC) | `CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC` |
| Arbiter | `GDKMJJGPM7ZFTDG6Y74O6JA2QCMQBEJJE7Q7I5FGKI77Z67XXY2C3LU2` |
| SDK | soroban-sdk 28 · Stellar CLI 27 |
| Record | `contracts/deployments/testnet.json` (tx hashes, wasm hash, smoke test) |

Redeploy with `make contract-deploy-testnet`. Deployer and arbiter keys live in the local Stellar CLI key store,
never in the repository.

## Model

- One escrow per bounty, keyed by `BytesN<32>` = `sha256("bountyflow:bounty:" || bounty_uuid || random_salt)`.
  The id is random (so nobody can pre-create a bounty's escrow) and stored in `bounty_escrows.onchain_bounty_id`.
  The backend only trusts an on-chain escrow whose terms match a `create_escrow` it prepared (see
  [security.md](security.md)).
- `reward_per_position × positions = required_amount`. Funding may be partial (`create_escrow` with an initial
  deposit, then `fund`). The escrow becomes `Funded` only when fully funded.
- Native XLM moves through the **Stellar Asset Contract** using the standard token interface. Any SAC-compatible
  token would work the same way; classic assets would need a trustline on the recipient.
- `assign` optionally locks a contributor on-chain. After that, the requester can refund only if the contributor
  consents (`consent_cancel`) or the deadline has passed.
- `release` pays exactly one position to a contributor, at most once (`AlreadyPaid`).
- Disputes: either party can `raise_dispute`, which freezes release and refund. The escrow's arbiter can only call
  `resolve_dispute`. That either pays the assigned contributor or releases their claim, so the requester can then
  refund. **The arbiter can never send funds to itself or to any other address.**
- There is no admin, no upgrade entry point and no withdrawal function. The deployed contract is immutable.

## Trust assumptions (summary)

1. Requesters trust that an approved payout will be signed. The contract cannot force a requester to release
   funds; disputes plus the arbiter cover that case, but only when the escrow is frozen on-chain.
2. Contributors who aren't locked on-chain (`assign`) can lose their claim to a refund. The UI recommends
   `ASSIGN` after accepting a contributor.
3. The arbiter is a single key controlled by platform moderators. It has bounded power (see above), but it is
   still a trust point. Mainnet should use a multisig arbiter.
4. The backend mirrors contract state for UX and analytics, but the contract is authoritative. Reconciliation
   always overwrites the DB view with chain state.

See `contracts/README.md` → *Trust assumptions and limitations* for the complete list.

## How the backend calls it

`app/blockchain/soroban.py` encodes each call. Argument order matches `lib.rs` exactly. `transactions.py` builds,
simulates, prepares and submits the call. `verification.py` checks signed envelopes and decodes results.
`reconciliation.py` maps the contract's `Escrow` struct onto `bounty_escrows`. Read-only calls (`get_escrow`,
`assignment`) are made through simulation, and nothing is submitted for them.
