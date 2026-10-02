# Secret rotation

Every secret BountyFlow holds, what rotating it breaks, how to rotate it, and how to prove it worked. Then two
ceremonies that are not ordinary rotations: the escrow contract admin key and the M-of-N arbiter set.

All secrets come from the environment (`.env`, gitignored and excluded from the Docker build context). The API,
the worker and every script read configuration at startup, so **every rotation needs both processes restarted**:

```bash
docker compose restart api worker
```

Rotate on a schedule, and immediately whenever a secret may have been exposed: in a log, a screenshot, a ticket,
a laptop that left, or a person who did.

## At a glance

| Secret | Rotating it ends | Blast radius | Planned cadence |
|---|---|---|---|
| `JWT_SECRET` | every session, every data-export download link, every saved-search unsubscribe link | all users | 12 months, or on exposure |
| `WALLET_CHALLENGE_SIGNING_SECRET` | in-flight wallet verifications | users mid-verification | 12 months |
| `STELLAR_SPONSOR_SECRET` | fee sponsorship and all passkey smart-wallet transactions until the new account is funded | contributors without XLM; every passkey wallet | 12 months, or on exposure |
| `STELLAR_ATTESTER_SECRET` | attestation writes until `set_attester` runs on-chain | reputation records | 12 months |
| `CREDENTIAL_ISSUER_SECRET` | verification of every already-issued credential | credential holders | 12 months |
| `METRICS_TOKEN` | Prometheus scraping | observability only | 6 months |
| `GITHUB_TOKEN` | the raised API rate limit | GitHub verification throughput | 6 months (or the token's own expiry) |
| `GITHUB_CLIENT_SECRET` | "Connect with GitHub" | OAuth linking only | 12 months |
| `GITHUB_WEBHOOK_SECRET` | webhook-driven pull request re-checks | freshness only | 12 months |
| `SMTP_PASSWORD` | outbound email | every notification email | per provider policy |
| Database credentials | everything | all users | 12 months |

## `JWT_SECRET`

**Signs:** access and refresh tokens (`HS256` by default, `app/core/security.py`).

**Also derives, by HMAC with a fixed label:**

- Data-export download links (`app/modules/compliance/exports.py`). The link key is
  `HMAC(JWT_SECRET, "<link label>")`, deliberately, so rotating `JWT_SECRET` invalidates every outstanding
  download link.
- Saved-search unsubscribe tokens (`app/modules/discovery/tokens.py`), which let someone turn a search's alerts
  off without signing in.
- In **development only**, the wallet-challenge signing key when `WALLET_CHALLENGE_SIGNING_SECRET` is empty.
  Production and mainnet refuse to start without an explicit one.

**Impact:** every signed-in user is signed out. Every data-export link already emailed stops working — the user
must request a new export. Every unsubscribe link already emailed stops working.

**Steps**

1. Generate:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   It must be at least 32 characters and must not contain `change-me`, `changeme`, `replace`, `dev-only`,
   `example` or `insecure` — the production and mainnet validators reject those.
2. Set `JWT_SECRET` in `.env` (or the secret manager).
3. Restart the API and the worker.
4. Tell support: users will be signed out, and anyone with a pending data export must request it again.

**Verify**

```bash
# A request with an old cookie is rejected; signing in again works.
curl -s -o /dev/null -w '%{http_code}\n' -b "bf_access=$OLD" http://127.0.0.1:8000/api/v1/users/me   # 401
```

Check `bountyflow_user_sessions` is not the source of truth here — the JWT itself no longer verifies, so the session
row is never reached.

**There is no overlap window.** The verifier holds one secret, and `JWT_ALGORITHM` is pinned to HMAC precisely so
no asymmetric or `none` confusion is possible. Rotate during a quiet period, or accept the mass sign-out.

## `WALLET_CHALLENGE_SIGNING_SECRET`

**What it is:** a Stellar secret seed (56 characters, starting with `S`) used **only** to sign wallet-ownership
challenges. It never holds funds and nothing it signs is ever submitted to the network.

**Impact:** challenges are issued for one user and one address, stored in Redis, and consumed on the first
verification attempt (`GETDEL`). A rotation invalidates challenges issued with the old key, so anyone mid-flow
sees the verification fail and starts again. Already-verified wallets are unaffected: the proof was checked at
verification time and the result is a row in `bountyflow_wallets`.

SEP-45 (smart wallets) also uses this key for the server's own authorization entry in the challenge pair, so the
same applies there.

**Steps**

1. Generate:

   ```bash
   python -c "from stellar_sdk import Keypair; print(Keypair.random().secret)"
   ```

2. Set `WALLET_CHALLENGE_SIGNING_SECRET`, restart the API and the worker.
3. Do **not** fund this account. It is a signing key, not a wallet.

**Verify**

```bash
# Issue a challenge and verify it end to end from the UI: Profile -> Wallets -> Connect.
# Or check the server accepts a fresh challenge it just issued (a full flow needs a wallet signature).
curl -s -X POST -b "bf_access=$TOKEN" -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"public_address":"G…"}' http://127.0.0.1:8000/api/v1/wallets/challenge | jq '.method'
```

`WALLET_CHALLENGE_HOME_DOMAIN` is public configuration, not a secret, and does not change on rotation.

## `STELLAR_SPONSOR_SECRET`

**What it is:** the platform fee sponsor. It pays the network fee on eligible contributor transactions (fee
bumps) and it is the transaction **source** for every passkey smart-wallet call and deployment.

**Impact of rotating:** fee sponsorship and passkey smart wallets are both off while the key is unset or the new
account is unfunded. A refused fee bump degrades gracefully — the user pays their own fee. A refused **relay**
does not: a contract account cannot be a transaction source, so a passkey wallet has no other way to transact and
the API says so.

**This key holds real funds. Drain the old account before you retire it.**

**Steps**

1. Generate and fund the new account.

   ```bash
   stellar keys generate bountyflow-sponsor-2 --network testnet --fund
   stellar keys address bountyflow-sponsor-2
   stellar keys show bountyflow-sponsor-2        # the S… seed, for .env
   ```

   On mainnet, fund it from treasury — there is no Friendbot. Fund it to the level the caps assume: it must sit
   well above `SPONSOR_LOW_BALANCE_XLM`, and far above `SPONSOR_MIN_BALANCE_XLM`.
2. Set `STELLAR_SPONSOR_SECRET` to the new seed and restart the API and the worker.
3. Confirm the new sponsor is live and funded:

   ```bash
   curl -s -b "bf_access=$TOKEN" http://127.0.0.1:8000/api/v1/admin/sponsorship | jq
   curl -s -H "Authorization: Bearer $METRICS_TOKEN" http://127.0.0.1:8000/metrics \
     | grep -E 'bountyflow_sponsor_(configured|balance_xlm)'
   ```

   `bountyflow_sponsor_configured` must be 1 and `bountyflow_sponsor_balance_xlm` must be above
   `bountyflow_sponsor_low_balance_threshold_xlm`.
4. **Drain the old account.** Wait until no transaction is still in flight from it
   (`bountyflow_chain_transactions_pending` at its normal level), then move its remaining XLM to treasury:

   ```bash
   stellar tx new payment --source-account bountyflow-sponsor \
     --destination <treasury G…> --asset native --amount <stroops> --network mainnet
   ```

   Leave the base reserve behind or the account cannot be merged; merge it only once you are certain nothing
   references it.
5. Only after draining, remove the old seed from every store.

`bountyflow_sponsored_transactions` keeps the historical rows; nothing needs migrating. The daily caps
(`SPONSOR_DAILY_TX_LIMIT`, `SPONSOR_DAILY_FEE_LIMIT_STROOPS`) are per user and per UTC day, not per sponsor, so
they are unaffected.

## `STELLAR_ATTESTER_SECRET`

**What it is:** the key that signs on-chain completion attestations. The attestation registry only accepts the
attester it currently holds, so the key and the contract are coupled.

**Impact:** the `attestation-pipeline` job cannot write until the registry knows the new key. Already-recorded
attestations keep the attester that wrote them and stay readable and verifiable.

**Steps**

1. Generate and fund the new key:

   ```bash
   python -c "from stellar_sdk import Keypair; print(Keypair.random().secret)"
   # then fund the derived public key (Friendbot on Testnet, treasury on mainnet)
   ```

2. Hand the role over on-chain, signed by the **current** attester:

   ```bash
   stellar contract invoke --id "$ATTESTATION_CONTRACT_ID" \
     --source-account bountyflow-attester --network testnet \
     -- set_attester --attester <current G…> --new_attester <new G…>
   ```

3. Set `STELLAR_ATTESTER_SECRET` to the new seed and restart the worker.
4. Confirm the contract agrees:

   ```bash
   stellar contract invoke --id "$ATTESTATION_CONTRACT_ID" \
     --source-account bountyflow-deployer --network testnet -- attester
   ```

**Verify:** watch `bountyflow_worker_job_consecutive_failures{job="attestation-pipeline"}` stay at 0 and
`bountyflow_worker_job_last_success_timestamp_seconds{job="attestation-pipeline"}` keep advancing. A wrong key
shows up as `Unauthorized` (error 3) from the registry.

Order matters: `set_attester` **first**, then the config. Swapping the config first makes the pipeline fail on
every run until the on-chain role catches up.

## `CREDENTIAL_ISSUER_SECRET`

**What it is:** the Ed25519 key that signs W3C verifiable credentials. It is the `did:web` issuer key, published
in the DID document at `/.well-known/did.json` as an Ed25519 Multikey (`z6Mk…`).

**Impact — read this before rotating.** The DID document carries exactly one verification method, derived from
`CREDENTIAL_ISSUER_SECRET`. There is **no key-history support**: BountyFlow does not publish the previous key
alongside the new one.

So after a rotation:

- The verification method id changes, because it is derived from the key.
- Every credential already issued was signed by the old key and names the old verification method id. It **no
  longer verifies** against this issuer: `POST /api/v1/credentials/verify` reports the issuer/proof check as
  failed, not as passed.
- Issuing is idempotent, and one of the things it treats as "changed" is the issuer key. So asking for the
  credential again re-issues it with the new key, and the re-issue **supersedes the old one** — the superseded
  credential's bit is set in the published Bitstring Status List at
  `GET /api/v1/credentials/status/revocation`.

That is the whole key-rotation story: old credentials are superseded and re-issued on demand, not verified
against an archived key. Anyone holding an old credential must fetch a new one.

**Steps**

1. Generate:

   ```bash
   python -c "from stellar_sdk import Keypair; print(Keypair.random().secret)"
   ```

2. Set `CREDENTIAL_ISSUER_SECRET`, restart the API.
3. Confirm the DID document and the issuer endpoint show the new key:

   ```bash
   curl -s http://127.0.0.1:8000/.well-known/did.json | jq '{id, assertionMethod}'
   curl -s http://127.0.0.1:8000/api/v1/credentials/issuer | jq
   ```

4. Tell credential holders to re-issue. Their old credential will verify as invalid at this issuer until they do.
5. Confirm the status list is still being signed and served:

   ```bash
   curl -s http://127.0.0.1:8000/api/v1/credentials/status/revocation | jq '.issuer'
   ```

Because of this, treat the issuer key as long-lived and rotate it only on a schedule or on exposure — not
casually. `CREDENTIAL_ISSUER_DOMAIN` is public configuration; changing it changes the DID itself, which is a
bigger change than a key rotation and has the same consequence for every issued credential.

## `METRICS_TOKEN`

**What it is:** the bearer token for `GET /metrics`. Without a token the endpoint answers only direct loopback
requests with no `X-Forwarded-For`; with the wrong token it answers **404**, not 401, so it never advertises
itself.

**Impact:** Prometheus stops scraping. Every alert built on those metrics silently stops evaluating, which is
worse than it sounds — nothing fires to tell you.

**Steps**

1. Generate (mainnet requires at least 24 characters):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Update the Prometheus side **first**, so the gap is as short as possible. With the bundled overlay the token
   comes from the `METRICS_TOKEN` environment variable and is written into a tmpfs inside the container, so:

   ```bash
   # .env
   METRICS_TOKEN=<new value>
   ```

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d prometheus
   docker compose restart api
   ```

   Prometheus re-reads `bearer_token_file` on every scrape, so once the file and the API agree, scraping
   resumes without a Prometheus reload.
3. In a managed setup, write the new token to the file `bearer_token_file` points at, then restart the API.

**Verify**

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $METRICS_TOKEN" \
  http://127.0.0.1:8000/metrics     # 200

curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer wrong" \
  http://127.0.0.1:8000/metrics     # 404
```

Then check the Prometheus target page shows `bountyflow-api` as `UP`.

## GitHub secrets

BountyFlow reads only public data from the GitHub REST API. All three of these are optional: without any of them
accounts are still proved with a public gist and pull requests are still verified, just at the unauthenticated
rate limit (60 requests an hour per IP), with caching and backoff.

### `GITHUB_TOKEN`

**Impact:** the rate limit drops from 5,000/hour to 60/hour. The `github-pr-recheck` job skips whole batches
while it is backing off, so pull request states go stale. Nothing breaks.

**Steps:** create a new fine-grained personal access token at
<https://github.com/settings/personal-access-tokens> with **no repository permissions and no account access**,
set `GITHUB_TOKEN`, restart the API and the worker, then revoke the old token.

**Verify:** `bountyflow_worker_job_last_success_timestamp_seconds{job="github-pr-recheck"}` keeps advancing and
the worker logs stop reporting rate-limit backoff.

### `GITHUB_CLIENT_SECRET`

**Impact:** "Connect with GitHub" (OAuth) stops working while the old and new values disagree. Gist proof is
unaffected, and accounts already linked stay linked — `bountyflow_github_accounts` records the method and the proof
URL.

**Steps:** in the OAuth app at <https://github.com/settings/developers>, generate a new client secret, set
`GITHUB_CLIENT_SECRET`, restart the API, then delete the old secret in GitHub. The callback stays
`<FRONTEND_URL>/app/settings/github/callback`.

**Verify:** complete one OAuth link from a test account.

### `GITHUB_WEBHOOK_SECRET`

**Impact:** the endpoint is `POST /api/v1/github/webhook` and it answers 404 while the value is empty. With a
mismatched secret, deliveries fail signature verification and are rejected. Pull requests are still re-checked
by the `github-pr-recheck` job every 30 seconds — you lose immediacy, not correctness.

**Steps:** generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`, set it on **both**
sides (GitHub's webhook configuration and `.env`), restart the API. Change GitHub first if you can tolerate a
few rejected deliveries; they are redelivered.

**Verify:** GitHub's webhook page shows recent deliveries with a 2xx response. Redeliver one from GitHub's UI.

## SMTP credentials

**Impact:** every outbound email stops — verification, password reset, notifications, data-export ready,
deletion notices. The `email-worker` consumer's handler fails and retries with backoff; after
`WORKER_MAX_RETRIES` the message goes to `email.events.dlq` or `notification.events.dlq`. Emails are unique per
idempotency key in `bountyflow_email_deliveries`, so a replay after the fix sends each one exactly once.

**Steps**

1. Create the new credential with the provider.
2. Set `SMTP_USERNAME` and `SMTP_PASSWORD` (and `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS=true` if they change).
3. Restart the worker — it is the process that sends.
4. Revoke the old credential with the provider.
5. Replay anything that dead-lettered during the gap ([kafka-lag-and-dlq.md](kafka-lag-and-dlq.md)).

**Verify:** trigger one real email (a password reset for a test account) and confirm it arrives. Check
`bountyflow_email_deliveries` for the new row.

## Database credentials

**Impact:** total. The API answers 503 on `/health/ready` without its database, and the worker's jobs fail.

**Steps — with no downtime** (managed PostgreSQL, where you can hold two roles):

1. Create a second role with the same grants, or set a new password on a second role that already exists.
2. Update `DATABASE_URL` (and `POSTGRES_USER` / `POSTGRES_PASSWORD` if the compose stack owns the database).
3. Restart the API and the worker. They open new connections with the new credential; the old pool drains.
4. Confirm, then revoke the old role's password.

**Steps — single role, brief downtime:**

```sql
ALTER ROLE bountyflow WITH PASSWORD '<new>';
```

then update `DATABASE_URL` and restart the API and the worker immediately. Existing connections survive the
`ALTER`, so the window is only as long as the restart.

Remember `TEST_DATABASE_URL` uses the same role locally, and any backup job with its own connection string needs
the new value too.

**Verify**

```bash
curl -s http://127.0.0.1:8000/health/ready | jq '.checks.database'   # "ok"
docker compose logs --tail=50 worker | grep -i 'database\|connection'
```

Mainnet refuses a `DATABASE_URL` that still carries a development password
(`bountyflow-local-dev-password`, or `:bountyflow@`).

---

# Ceremony: the escrow contract admin key

This is not a normal secret. The escrow contract's admin can call `upgrade(new_wasm_hash)`, which **replaces the
contract's code while keeping the contract id and every escrow in storage**. A malicious upgrade could move
escrowed funds. It is the most sensitive key of the deployment.

The admin cannot touch escrow funds through the contract's ordinary interface. It can only replace the code and
hand over the role. That is enough to make it the key that matters most.

## How it must be held

| Requirement | Why |
|---|---|
| A hardware wallet, or a Stellar account with multisig thresholds set so no single person can sign. | One compromised laptop must not be able to replace the contract code. |
| On mainnet, multisig with a quorum of at least 2 of 3. | The same reason disputes need `STELLAR_ARBITER_THRESHOLD >= 2`. |
| Held by named people, recorded below, each with a documented recovery path. | A key nobody can find is as bad as a key anyone can use. |
| Never in `.env`, never in the repository, never in CI. | It is not application configuration. The backend never calls `upgrade`. |
| Every use announced in advance and recorded afterwards. | `contract_upgraded` is an event anyone can watch; an unannounced one is an incident. |

The deploy scripts keep it in the local Stellar CLI key store as the identity `bountyflow-escrow-admin`
(`ADMIN_IDENTITY`), which is fine for Testnet and **not** acceptable for mainnet.

Record the holders here before mainnet:

| Signer | Holder | Device / custody | Recovery | Public key |
|---|---|---|---|---|
| 1 | — | — | — | — |
| 2 | — | — | — | — |
| 3 | — | — | — | — |
| Quorum | at least 2 of 3 | | | |

The Testnet deployment's admin is `GAXPFJGPZ2X2DLQWKLQKUAX55MBY7SRXHK2HGC2KAV5QHOP6QCSDD26R`
(`contracts/deployments/testnet.json`).

## Rotating the admin

`set_admin(new_admin)` requires **both** the current admin and the new admin to sign, so the role cannot be sent
to a mistyped address. It emits `admin_changed` with the previous and the new admin.

Present in the room (or on the call): both key holders, one witness, one person recording.

1. **Prepare.** Confirm the new admin account exists on the network and is funded. Read the current admin back
   from the contract so nobody is working from a stale note:

   ```bash
   stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
     --source-account bountyflow-deployer --network mainnet -- admin
   ```

2. **Rehearse on Testnet** with the same key types, the same tooling and the same people. A hardware wallet that
   nobody has used with the Stellar CLI before is not something to discover on mainnet.
3. **Execute.** Both admins sign the same invocation:

   ```bash
   stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
     --source-account bountyflow-escrow-admin --network mainnet \
     -- set_admin --new_admin <new admin G…>
   ```

   With a multisig account, collect the signatures on the same envelope before submitting.
4. **Verify** from a second machine:

   ```bash
   stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
     --source-account bountyflow-deployer --network mainnet -- admin
   ```

   and confirm the `admin_changed` event in the explorer at
   `{STELLAR_EXPLORER_BASE_URL}/contract/{SOROBAN_CONTRACT_ID}`.
5. **Record.** Update the table above and `contracts/deployments/<network>.json`. Note the transaction hash.
6. **Retire the old key.** Destroy it, or move it to cold storage with a written note that it is no longer the
   admin. Do not leave it usable and unlabelled.

Nothing in the backend changes: the admin is not configuration and the API never calls `upgrade` or `set_admin`.

See [contract-upgrade.md](contract-upgrade.md) for the upgrade procedure itself.

---

# Ceremony: the M-of-N arbiter key set

Arbiters resolve disputes. Each escrow stores **the arbiter set and threshold it was created with**, so changing
the configuration affects new escrows only — every existing escrow keeps voting with the arbiters it already
has. That is a feature, not a limitation: nobody can change who decides a dispute after the money is in.

Arbiter power is bounded by the contract: an arbiter can pay the assigned contributor up to their open position,
with the rest going back to the requester, or remove the assignment. **Arbiters can never send funds to
themselves or to any address other than the contributor and the requester.**

## Requirements

| Requirement | Detail |
|---|---|
| `STELLAR_ARBITER_THRESHOLD >= 2` on mainnet | `app/core/mainnet.py` refuses to start otherwise. |
| `STELLAR_ARBITER_ADDRESSES` lists at least `STELLAR_ARBITER_THRESHOLD` **distinct** signers | Also enforced at startup. |
| Signer keys generated on separate machines, by separate people | The threshold is meaningless if one person generated all the keys. |
| Only public keys are ever recorded | The addresses are public configuration. The seeds never leave their holder. |

A sensible mainnet shape is 2 of 3: three holders in different places, any two can resolve a dispute, no single
person can.

## Generating the keys

Each holder does this **on their own machine**, and the machine should be air-gapped or at least freshly booted
and offline for the generation step. Nobody else watches the screen and nobody else takes the output.

```bash
# Offline. Generates a keypair; nothing is sent anywhere.
python -c "from stellar_sdk import Keypair; k = Keypair.random(); print(k.public_key); print(k.secret)"
```

or, with the Stellar CLI, into that machine's own key store:

```bash
stellar keys generate bountyflow-arbiter-2          # generation only; do not pass --fund here
stellar keys address bountyflow-arbiter-2           # the public key: this is what you share
```

Rules for the holder:

- **Only the public key (`G…`) leaves the machine.** Read it out loud and have it read back before it is
  written down.
- The seed goes to a hardware wallet or offline storage with a documented recovery path.
- The account must exist on the network to sign, so fund it with the minimum reserve from treasury — as a
  separate step, after the public key is recorded.
- Never generate two signer keys on the same machine.

## Recording the set

| Signer | Holder | Public key | Custody | Recovery | Recorded by | Date |
|---|---|---|---|---|---|---|
| 1 | — | — | — | — | — | — |
| 2 | — | — | — | — | — | — |
| 3 | — | — | — | — | — | — |
| Threshold | | 2 | | | | |

Then set the configuration (public values, not secrets):

```bash
# .env
STELLAR_ARBITER_ADDRESSES=G...1,G...2,G...3
STELLAR_ARBITER_THRESHOLD=2
```

and restart the API and the worker. New escrows will be created with this set; existing ones keep theirs.

The Testnet deployment already runs 2 of 3 — see `contracts/deployments/testnet.json` and
[`docs/smart-contracts.md`](../smart-contracts.md).

## Test on Testnet first

Do not let the first real dispute vote be the first time these keys have voted.

1. Point a Testnet stack at a contract with the same shape (`MIN_REVIEW_WINDOW=60`,
   `ARBITER_ADDRESSES`, `ARBITER_THRESHOLD=2` on `scripts/deploy-contract.sh`).
2. Run a full dispute: fund a bounty, assign a contributor, `raise_dispute`, then have **two different holders**
   each cast a `vote_resolution` for exactly the same resolution.
3. Confirm:
   - the first vote records but does not execute (`bounty.dispute_vote_recorded`, "1 of 2 arbiter approvals");
   - the second vote executes the resolution and the funds move;
   - `bountyflow_dispute_votes` has one row per arbiter and dispute round, and the escrow's `dispute_round` advanced;
   - each holder could actually sign with their own device, unaided.

```bash
# Read the recorded votes for an escrow at any point.
stellar contract invoke --id "$SOROBAN_CONTRACT_ID" \
  --source-account bountyflow-deployer --network testnet \
  -- resolution_votes --bounty_id <64 hex escrow id>
```

## Rotating an arbiter

1. Generate the replacement key as above.
2. Update `STELLAR_ARBITER_ADDRESSES` (and `STELLAR_ARBITER_THRESHOLD` if the shape changes) and restart the API
   and the worker.
3. **Existing escrows keep the old set.** Do not assume the departing holder is out of the loop: they remain an
   arbiter for every escrow created before the change, until those escrows are completed or cancelled. Find them:

   ```sql
   SELECT bounty_id, onchain_bounty_id, state, arbiter_addresses, arbiter_threshold
   FROM bountyflow_bounty_escrows
   WHERE state IN ('AWAITING_FUNDING', 'FUNDED', 'CANCEL_REQUESTED', 'DISPUTED')
     AND '<departing G…>' = ANY (arbiter_addresses);
   ```

4. Decide per escrow: usually, let it run out. If a departing holder's key is **compromised** rather than just
   retired, that is an incident, not a rotation — the remaining quorum must be able to outvote it, and if the
   threshold makes that impossible, escalate to the contract owners immediately.
5. Record the change in the table above with the date.
