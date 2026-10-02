# Escrow contract upgrade

From v2 on, the escrow contract is upgradeable: `upgrade(new_wasm_hash)` replaces the code while keeping the
contract id and every escrow in storage. Only the admin set at deployment can call it, and every upgrade emits
`contract_upgraded`.

An upgrade can move escrowed funds if the new code says so. Treat it as the highest-risk change this system
has: it is a release, a key ceremony and a money operation at once.

## Before you start

| Requirement | Why |
|---|---|
| The new wasm is audited, or the change is trivial and reviewed by at least two people. | The code that holds the money is being replaced. |
| Storage layout is preserved. `Escrow` fields may only be **appended**. | Existing escrows are read with the new code. |
| `CONTRACT_VERSION` is bumped when the interface changes. | The backend reads `version()` to decide which interface to use. |
| The whole procedure has been run on Testnet against a contract with real escrows in it. | Not a dry run on an empty contract. |
| Admin key holders are available and have rehearsed. | See the ceremony in [secret-rotation.md](secret-rotation.md). |
| A rollback wasm hash is already uploaded and recorded. | Rolling back is another upgrade; do not be uploading it under pressure. |
| An announced window, and the on-call knows. | `contract_upgraded` from nowhere is a SEV1 by default. |

## 1. Build reproducibly

```bash
cd contracts
cargo fmt --all --check
cargo clippy --all-targets -- -D warnings
cargo test -p bounty_escrow
stellar contract build --package bounty_escrow --locked
ls -l target/wasm32v1-none/release/bounty_escrow.wasm
```

`--locked` makes cargo refuse to update `Cargo.lock`, which is what keeps the build reproducible. The wasm must
be built with `stellar contract build` from stellar-cli v25.2.0 or newer: soroban-sdk 28 relies on the CLI to
strip unreachable spec entries, and a plain `cargo build --target wasm32v1-none` stops in soroban-sdk's build
script.

**The wasm hash depends on the toolchain.** Rust 1.96 with Stellar CLI 27.0.0 reproduces the currently deployed
Testnet wasm (`f9b88bca…0d8a`). CI builds with the current stable Rust, so its hash can legitimately differ.
Pin both, and have a second person build independently and compare hashes before you go near the network:

```bash
sha256sum contracts/target/wasm32v1-none/release/bounty_escrow.wasm
rustc --version
stellar --version
```

Two independent builds that disagree is a stop condition, not a curiosity.

## 2. Upload and record the hash

Uploading only puts the code on the ledger. Nothing uses it until `upgrade` points a contract at it, so this
step is safe to do early and from an ordinary funded account.

```bash
HASH=$(stellar contract upload \
  --wasm contracts/target/wasm32v1-none/release/bounty_escrow.wasm \
  --source-account bountyflow-deployer --network mainnet)
echo "$HASH"
```

Record, in the change ticket and in `contracts/deployments/<network>.json`:

| Field | Value |
|---|---|
| New wasm hash | |
| Upload transaction | |
| Previous wasm hash (the rollback target) | |
| Builder, Rust version, Stellar CLI version | |
| Second builder's hash | |
| Audit report and its sha256 | |
| Commit | |

## 3. Dry run on Testnet

Against a Testnet contract that has live escrows in it, not an empty one.

```bash
TESTNET_ID=CBCXG46FJPYBPWYZ24BWFVNJ6G2ILFAXHX2COETDNXYE6C5IJWAZ3M4C

# Read state BEFORE, for a known escrow.
stellar contract invoke --id "$TESTNET_ID" --source-account bountyflow-deployer --network testnet \
  -- get_escrow --bounty_id <64 hex escrow id>

stellar contract upload --wasm contracts/target/wasm32v1-none/release/bounty_escrow.wasm \
  --source-account bountyflow-deployer --network testnet
# -> TESTNET_HASH

stellar contract invoke --id "$TESTNET_ID" \
  --source-account bountyflow-escrow-admin --network testnet \
  -- upgrade --new_wasm_hash "$TESTNET_HASH"
```

Then prove, on Testnet, that:

- `get_escrow` for that same escrow returns **identical** values afterwards;
- `version()` is what you expect;
- a full lifecycle still works end to end — `make test-testnet` runs fund, apply, accept, submit, revise,
  approve, pay out, verify, and reject a duplicate payout against the real network;
- the backend is happy: point a staging API at the upgraded contract and confirm it does not fall back to the v1
  interface (it reads `version()` and only uses v2 features when the answer is `2`).

Do not go to mainnet until all four pass.

## 4. The signing ceremony

Same people and process as the admin rotation in [secret-rotation.md](secret-rotation.md): both or all required
key holders present, one witness, one recorder.

1. Read the current admin back from the contract, so nobody is working from a note:

   ```bash
   stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
     --source-account bountyflow-deployer --network mainnet -- admin
   ```

2. Read the wasm hash out loud, character group by character group, and have it read back. A wrong hash here
   replaces the code with something else entirely.
3. Collect the signatures. With a multisig admin account, build the envelope once and collect signatures on
   **that** envelope; do not let each signer construct their own.
4. Submit:

   ```bash
   stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
     --source-account bountyflow-escrow-admin --network mainnet \
     -- upgrade --new_wasm_hash "$HASH"
   ```

5. Record the transaction hash immediately.

## 5. Verify

Run all of these, from a machine that was not used to sign.

```bash
# The admin is unchanged.
stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
  --source-account bountyflow-deployer --network mainnet -- admin

# The interface version is what the new code declares.
stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
  --source-account bountyflow-deployer --network mainnet -- version

# A known escrow reads back exactly as it did before the upgrade.
stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
  --source-account bountyflow-deployer --network mainnet \
  -- get_escrow --bounty_id <64 hex escrow id>

# The minimum review window survived.
stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
  --source-account bountyflow-deployer --network mainnet -- min_review_window
```

Then the platform side:

- `contract_upgraded` appears once, with your hash, at
  `{STELLAR_EXPLORER_BASE_URL}/contract/{SOROBAN_CONTRACT_ID}`.
- Wait for one `reconciliation-audit` cycle (600 s) and confirm `bountyflow_reconciliation_mismatches` and
  `bountyflow_reconciliation_foreign_escrows` are both 0. This is the real test: it compares every live escrow
  against the new code.
- Watch `bountyflow_http_requests_total{status=~"5.."}` on the chain routes and
  `bountyflow_chain_transactions_failed_24h`.
- Do one real end-to-end action on a low-value bounty and watch it confirm.

## 6. Rollback

Rolling back is another upgrade, pointing at the previous wasm hash.

```bash
# The previous wasm is usually still on the ledger. If it is not, upload it again from the tagged commit.
stellar contract upload --wasm <previous bounty_escrow.wasm> \
  --source-account bountyflow-deployer --network mainnet
# -> PREVIOUS_HASH (this must equal the hash you recorded in step 2)

stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
  --source-account bountyflow-escrow-admin --network mainnet \
  -- upgrade --new_wasm_hash "$PREVIOUS_HASH"
```

Then run every verification in step 5 again.

Rollback is only safe when the new code did not change the storage layout in a way the old code cannot read. If
the new version **appended** fields to `Escrow` and any escrow has been written since the upgrade, the old code
may not be able to read those rows. That is why storage changes are append-only and why the rollback decision
has to be made before the upgrade, not after.

## Escrows on the v1 contract stay on v1

v1 (`CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY`) has no admin and no `upgrade` entry point, which
is why v2 is a new contract rather than an upgrade of v1. Escrows created on v1 **stay on v1 and keep working**,
with the v1 feature set: whole-position payouts and a single arbiter.

This is why the backend must keep resolving a contract id **per escrow**. Every `bountyflow_bounty_escrows` row
stores its own `contract_id` and `contract_version`, and every call for that escrow goes to that contract
(`soroban.on_contract`). `SOROBAN_CONTRACT_ID` decides only where **new** escrows are created.

Consequences to keep in mind:

- Upgrading the v2 contract does not touch v1 escrows at all. They are a different contract.
- A v2-only action on a v1 escrow is refused by the API with `409 invalid_state_transition` and an explanation.
  That is correct, not a bug to route around.
-  - Never rewrite `bountyflow_bounty_escrows.contract_id` to "migrate" an escrow. The money is in the other
  contract; the row would then point at an escrow that does not exist.
- The mainnet guard checks the **configured** ids, not per-escrow ones, for exactly this reason.

Deploying a v3 would follow the same shape: deploy it, point `SOROBAN_CONTRACT_ID` at it for new escrows, and
leave v1 and v2 escrows where they are.

## Emergency measures: be honest about what you have

**There is no pause entry point.** The escrow contract has no `pause`, no `freeze`, no admin withdrawal, and no
way for anyone — including the admin — to stop a `claim`, a `release` or a `refund` that the contract's own rules
allow. This is deliberate: the contract is permissionless so that a requester cannot be stopped from paying and a
contributor cannot be stopped from claiming.

So every emergency measure is **application-level**. They stop new activity; they do not touch funds already in
escrow.

| Measure | How | Effect |
|---|---|---|
| Stop preparing new chain transactions | Point `SOROBAN_CONTRACT_ID` away from the affected contract, or unset it, and restart the API. | No new escrows are created and no new prepares are built for it. Existing escrows keep working directly on-chain, because the contract is public. |
| Make the API read-only | Take the API to a read-only deployment, or block the mutating routes at the proxy. | Nothing new is prepared or submitted through us. |
| Disable funding in the UI | Ship a frontend build with funding and payout actions hidden. | Users stop being led into the affected flow. |
| Stop the worker | `docker compose stop worker`. | No verification, no reconciliation, no settlement. Use only if settlement itself is what is causing harm; it makes the database go stale, not safe. |
| Disable a reward asset | `/admin/assets`, set `is_enabled` false. | No new bounties in that asset. Money already in escrow is untouched. |
| Turn off fee sponsorship | Unset `STELLAR_SPONSOR_SECRET`, restart. | Fee bumps stop (users pay their own fees) and passkey smart wallets cannot transact at all. |

What you **cannot** do:

- **You cannot freeze escrowed funds.** Anyone can call the contract directly through any RPC provider with
  their own wallet. Taking BountyFlow offline does not stop them.
- **You cannot claw back a payout.** Once `release`, `claim` or a dispute resolution has executed, the transfer
  is final.
- **You cannot stop a claim after the review window passes.** That is the contract's guarantee to contributors
  and there is no override.
- **You cannot resolve a dispute unilaterally.** Resolution needs `STELLAR_ARBITER_THRESHOLD` approvals from the
  arbiter set that escrow was created with.
- **You cannot change an existing escrow's arbiter set, threshold or review window.** They are fixed at
  creation.

The only thing that changes contract behaviour is `upgrade`, which is this whole runbook, needs the admin
quorum, and is not an emergency tool. If the situation genuinely calls for it, declare a SEV1, get the key
holders, and run the procedure properly — a rushed upgrade to the contract that holds the money is how a bad
day becomes a worse one.
