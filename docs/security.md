# Security

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [Compliance](compliance.md) &middot; [Blockchain](blockchain.md) &middot; [GitHub](github.md) &middot; [Reporting a vulnerability](../SECURITY.md)
<!-- nav -->

This document describes how BountyFlow protects accounts, money and data, and records the results of the
security review of 2026-09-26 (backend and escrow contract). It is the reference for the security regression
suite in `backend/tests/integration/security/`.

- [Threat model](#threat-model)
- [Authentication and sessions](#authentication-and-sessions)
- [CSRF](#csrf)
- [Authorization (RBAC and ownership)](#authorization)
- [Wallet ownership proof](#wallet-ownership-proof)
- [GitHub account proof and webhook](#github-account-proof-and-webhook)
- [Bounty Q&A](#bounty-qa)
- [Transaction verification pipeline](#transaction-verification-pipeline)
- [Escrow contract: trust assumptions and limitations](#escrow-contract-trust-assumptions-and-limitations)
- [Input handling](#input-handling)
- [Rate limits and client IP](#rate-limits-and-client-ip)
- [Transport, headers and CORS](#transport-headers-and-cors)
- [Secrets management](#secrets-management)
- [Logging and redaction](#logging-and-redaction)
- [Dependency scanning](#dependency-scanning)
- [Review findings (2026-09-26)](#review-findings-2026-09-26)
- [Known limitations and recommendations for mainnet](#known-limitations-and-recommendations-for-mainnet)

## Threat model

### Assets

| Asset | Where it lives | Why it matters |
|---|---|---|
| Escrowed funds (XLM) | Soroban escrow contract | Contributors' rewards and requesters' deposits |
| Financial records | `bountyflow_bounty_escrows`, `bountyflow_blockchain_transactions`, `bountyflow_payment_records` | Shown as "funded", "paid", reputation totals |
| Accounts and sessions | `bountyflow_users`, `bountyflow_user_sessions`, cookies | Account takeover leads to chain actions with the victim's verified wallet |
| Wallet-to-account links | `bountyflow_wallets` | Payout destinations are derived from them |
| Private content | Applications (review notes), submissions, disputes, drafts, notifications | Confidentiality between parties |
| Server secrets | `JWT_SECRET`, `WALLET_CHALLENGE_SIGNING_SECRET`, SMTP and DB credentials | Token forgery, wallet-proof forgery |
| Sponsor balance | `STELLAR_SPONSOR_SECRET`'s account | Pays other people's network fees; a drained sponsor stops passkey wallets working |
| Passkey smart wallets | Soroban contract accounts, signer = a WebAuthn key on the user's device | They hold funds and are payout destinations; the device's passkey is the only key |

### Actors

| Actor | Capabilities assumed |
|---|---|
| Anonymous internet user | Any HTTP request, any header, spoofed `X-Forwarded-For`, cross-site requests from a malicious page |
| Registered user (requester / contributor) | A verified wallet; can sign arbitrary Stellar transactions and **call the escrow contract directly**, bypassing BountyFlow |
| Moderator / Admin | Staff permissions from the RBAC matrix; can be a party to a bounty |
| Arbiter key holder | Signs `resolve_dispute` on-chain; bounded by the contract |
| Third party on-chain | Can create escrows at any `bounty_id` with any token, arbiter and deadline |
| Sponsorship abuser | A registered user who wants BountyFlow to pay for transactions of their choosing, or to drain the sponsor |
| Infrastructure failure | Redis, Kafka or the RPC being down |

Out of scope: a compromised host or database, a compromised browser wallet, and bugs in Stellar Core or the
Soroban host.

### Trust boundaries

```
 Browser (SPA, wallet)  ──HTTPS──>  nginx  ──>  FastAPI API  ──>  PostgreSQL (source of truth)
        │                                          │  │  └─────>  Redis (cache, rate limits, challenges, locks)
        │ signs XDR prepared by the API            │  └────────>  outbox ──> Kafka ──> worker (emails, verification)
        └──────────────── submits (optionally) ───>│
                                                   └──────────>  Soroban RPC ──> escrow contract (funds)
```

1. **Browser → API.** Everything from the client is untrusted: bodies, headers, cookies, and every transaction
   it signs. Amounts, destinations and contract arguments are always derived on the server.
2. **API → chain.** The contract is the authority for funds. The database is a view of chain state and is only
   updated from **verified** chain state of an escrow BountyFlow itself prepared (SEC-01).
3. **Chain → API.** The contract is public. Any account can call it directly, so on-chain state is attacker-
   influenced and must be checked before it is believed.
4. **API → Redis.** Redis is an optimisation. Losing it must never allow a double effect (row locks and unique
   constraints are the real guards). Wallet challenges fail closed.
5. **Worker.** Consumes only events the API wrote to the outbox. Payloads never carry secrets or raw tokens.

## Authentication and sessions

| Control | Implementation |
|---|---|
| Password hashing | Argon2id, `t=3`, `m=64 MiB`, `p=2`, 16-byte salt (`app/core/security.py`), above the OWASP baseline. Hashes are upgraded on login when parameters change. |
| Hashing off the event loop | `hash_password_async` / `verify_password_async` run on a dedicated 4-thread pool. This keeps a login from stalling the API (~100 ms per hash) and caps concurrent Argon2 memory at 256 MiB (SEC-04). |
| Password policy | 10 to 128 characters, at least 2 character classes, no leading or trailing whitespace. |
| Timing-safe login | An unknown email still verifies against a precomputed dummy hash. Suspension is only revealed after a correct password. |
| Access token | JWT, HMAC only (`HS256` default; the setting is limited to `HS256/384/512`, SEC-10). Validated: signature with pinned algorithm list, `iss`, `exp`, required `sub`/`sid`/`type`, `type == "access"`. TTL 15 min. Contains the session id, and every request checks that the session exists, is not revoked or expired, and the user is active. Permissions come from the database role, never from the token's `role` claim, so a demotion is immediate. |
| Refresh token | Opaque `<session_id>.<256-bit secret>`. Only the SHA-256 is stored. Rotated on every use; the previous hash is kept, and presenting it again revokes the session (reuse detection). The session row is locked (`FOR UPDATE`) while rotating. A token is bound to its session id. |
| Revocation | Logout, per-session revoke (`DELETE /auth/sessions/{id}`, ownership-checked), password reset (all sessions), suspension (all sessions and 403 on every request). |
| Email verification / reset tokens | 256-bit random, SHA-256 at rest, single use (`used_at`), expiry 24 h / 1 h. Issuing a new token invalidates older ones. They are issued by the email worker at send time and never placed on Kafka or in logs. |
| Account enumeration | Forgot-password always answers 202 with the same message. Registration returns 409 for a taken email (accepted risk SEC-14, rate-limited). |
| Seeded accounts | Created only by the development seed, which refuses to run in `staging`/`production` (startup skips it there too). They are ordinary accounts that sign in through `POST /auth/login`; there is no passwordless or shortcut login route (tested). |

### Cookies

| Cookie | HttpOnly | Secure | SameSite | Path | Lifetime |
|---|---|---|---|---|---|
| `bf_access` | yes | `COOKIE_SECURE` (required `true` in staging/production) | `COOKIE_SAMESITE` (default `lax`) | `/` | 15 min |
| `bf_refresh` | yes | same | same | `/api/v1/auth` | 30 days |
| `bf_csrf` | **no** (double-submit) | same | same | `/` | 30 days |

## CSRF

- **Double-submit cookie.** Every non-safe request (`POST`, `PUT`, `PATCH`, `DELETE`) must carry
  `X-CSRF-Token` equal to the `bf_csrf` cookie. The comparison is constant-time. This holds for all paths, not
  only `/api/v1` (`CSRFMiddleware`).
- **Exempt routes, matched exactly** (SEC-13): `POST /auth/register`, `/auth/login`, `/auth/refresh`,
  `/auth/forgot-password`, `/auth/reset-password`, `/auth/verify-email`. These either create
  the session (no token exists yet) or are protected by single-use secrets.
- **Visitors get a token too.** Signing in mints `bf_csrf`; a request from someone who has never signed in gets
  one on the response to their first safe request (`CSRFMiddleware`, `HttpOnly` off on purpose). That is what
  lets the one route open to visitors — `POST /feedback` — stay behind the same check instead of being exempted.
- **Why exempt routes are still safe from cross-site forms.** They accept JSON only. A cross-site HTML form can
  send `text/plain`, urlencoded or multipart bodies, and FastAPI answers 422 for all of them (tested). Cookies
  default to `SameSite=Lax`.
- **Coverage is enforced by a test.** `test_every_mutating_route_requires_csrf` enumerates every mutating
  operation in the OpenAPI document and asserts 403 `csrf_failed` without the header or with a forged header,
  except the exempt list.
- Limitation (SEC-15): the token is not bound to the session. An attacker who can set cookies for the site
  (for example from a compromised sibling subdomain) could plant a known token. See recommendations.

## Authorization

Two layers: **RBAC permissions** (`app/core/rbac.py`, enforced by `require_permission` dependencies and
`ensure_permission` in services) and **ownership checks** in services. Suspended accounts have no permissions and
get 403 on every authenticated request.

### Permission matrix

| Permission | USER | MODERATOR | ADMIN |
|---|:---:|:---:|:---:|
| `bounty:create`, `application:create`, `dispute:raise`, `report:create`, `wallet:manage` | ✓ | ✓ | ✓ |
| `bounty:moderate`, `bounty:feature`, `bounty:view_all` | | ✓ | ✓ |
| `application:view_all`, `submission:view_all`, `dispute:view_all`, `transaction:view_all` | | ✓ | ✓ |
| `dispute:resolve`, `report:review`, `feedback:review`, `user:view_all`, `audit:read`, `analytics:platform`, `system:health` | | ✓ | ✓ |
| `user:manage` (suspend/reactivate), `user:assign_role` | | | ✓ |

Nobody can change their own role or status. Role changes need `user:assign_role`. Moderators cannot promote,
demote, suspend or reactivate anyone. A moderator who is a party to a dispute cannot take or resolve it.

### Route classes

| Class | Routes | Guard |
|---|---|---|
| Public (no session) | `GET /config/public`, `/bounties`, `/bounties/featured`, `/bounties/{ref}`, `/bounties/{ref}/activity`, `/bounties/{id}/funding`, `/bounties/{id}/transactions`, `/transactions/{ref}`, `/users/{username}[/bounties\|/contributions\|/stats]`, `/analytics/public`, `POST /feedback`; the CSRF-exempt auth routes; `POST /auth/logout` | Visibility filters: drafts and hidden bounties return 404 unless you are the owner or hold `bounty:view_all`; unsigned or expired transactions are only visible to their creator or `transaction:view_all` |
| Authenticated | Everything else | Session (and permission where listed) |
| Staff | `/admin/*`, `GET /analytics/platform`, `POST /bounties/{id}/feature`, `POST /disputes/{id}/assign`, `POST /disputes/{id}/resolve` | `require_permission(...)` (see `app/modules/admin/router*.py`) |

`test_every_non_public_route_requires_authentication` and `test_staff_routes_reject_ordinary_users` enumerate
the OpenAPI document, so a new route fails CI until it is classified.

### Ownership rules (IDOR)

| Resource | Rule |
|---|---|
| Bounty authoring, publish, cancel | Requester only (moderators may cancel through moderation) |
| Applications of a bounty | Requester or `application:view_all`. `review_note` is never shown to the contributor. |
| Withdraw an application | The contributor who applied (others get 404) |
| Submissions | Contributor, the bounty's requester, or `submission:view_all`. Reviews: requester only. |
| Disputes | Parties (raiser, disputed contributor, requester) or `dispute:view_all`. Evidence: parties or `dispute:resolve`. |
| Notifications, preferences, wallets, sessions, `/…/me` lists | The owner only (queries filter on `user_id`) |
| Transactions | Submit: the creator only (404 otherwise). Read: see public class above. |
| Chain actions | `FUND`/`ASSIGN`/`PAYOUT`/`REQUEST_CANCEL`/`REFUND`: requester, signing with a wallet **they** verified that also matches the escrow's on-chain requester. `CONSENT_CANCEL`: the on-chain-assigned contributor with their locked wallet. `RAISE_DISPUTE`: a party. `RESOLVE_DISPUTE`: `dispute:resolve` and the escrow's arbiter wallet (the contract enforces the arbiter's signature). |

`test_idor_matrix`, `test_role_escalation_is_impossible` and `test_suspension_revokes_every_session` cover
these rules.

## Wallet ownership proof

A wallet is linked only after a SEP-10 style challenge (`app/blockchain/wallet.py`):

1. `POST /wallets/challenge` builds a challenge transaction (a `manage_data` op with a random nonce, sourced
   from the claimed address, 300 s time bounds) signed by a dedicated server key
   (`WALLET_CHALLENGE_SIGNING_SECRET`, never funded, required in production). The challenge hash is stored in
   Redis under `(user_id, address)`, which binds it to the requesting account.
2. `POST /wallets/verify` atomically **consumes** the challenge (`GETDEL`), so it is single use even when
   verification fails. It checks that the signed envelope's hash equals the issued challenge, that the server
   signature, time bounds, home and web-auth domains are valid, and that the client master key signed it
   (`verify_challenge_transaction_signed_by_client_master_key`). The challenge is never submitted.
3. Only a real ed25519 signature from the claimed address proves ownership. There is no bypass or
   development marker; wallets are stored per network label, so a testnet wallet is never used on mainnet.
4. A partial unique index (`public_address, network` WHERE `VERIFIED`) guarantees one owner per address. A
   second account that proves the same key gets 409.
5. If Redis is unavailable, challenges fail **closed** (503).

Two more proofs exist for wallets that cannot sign a challenge transaction. Both are issued, stored and consumed
exactly like the SEP-10 one, and the record carries its method, so an answer of the wrong kind is refused:

6. **SEP-53 signed message** (`G…`). The wallet signs `sha256("Stellar Signed Message:\n" + message)`; the
   message names the address, the network, a 24-byte nonce and an expiry, and the signature is verified against
   the claimed account key. Same guarantee as SEP-10 — only the account's own ed25519 key produces it.
7. **SEP-45 web authentication** (`C…`, smart wallets). The challenge is a pair of Soroban authorization entries
   for `web_auth_verify` on BountyFlow's own web-auth contract. The server keeps **its** signed entry from the
   issued challenge and takes only the entry whose credential address is the claimed wallet, refusing it unless
   the authorized invocation is byte-identical to the issued one and actually carries a signature. It then
   verifies by simulation: the call succeeds only if the wallet's `__check_auth` accepts, and the parsed nonce
   and account must equal the issued ones. Nothing is submitted. A client cannot substitute the server's entry,
   replay another wallet's entry, or have a different call authorized.

### Sponsorship abuse

The sponsor pays for other people's transactions, so it is a spendable asset. Defences
(`app/blockchain/sponsorship.py`), all checked again at submission time, all failing closed:

- **Nothing user-chosen is sponsored.** The contract id, function name and arguments of a sponsored transaction
  are the ones BountyFlow set at prepare time and stored on the row; a fee bump wraps that exact inner
  transaction, whose hash the server already pinned. A user cannot present an arbitrary envelope for a fee bump.
- **Only contributor-side calls**: `consent_cancel`, `raise_dispute`, `submit_work`, `claim`, and only when the
  caller is not the bounty's requester. Requester-side calls, which move money out of escrow, are never
  sponsored. Trustline sponsorship is limited to the assets in `SPONSOR_ALLOWED_ASSETS`.
- **Caps**: a per-transaction fee ceiling, and a per-user daily count and fee budget counted from
  `bountyflow_sponsored_transactions` under a per-user advisory lock taken in the same transaction as the insert, so
  concurrent submissions cannot both pass the cap.
- **Floor**: sponsorship stops below `SPONSOR_MIN_BALANCE_XLM` and the admin console warns below
  `SPONSOR_LOW_BALANCE_XLM`. Every sponsored transaction is recorded with the fee the network actually charged.
- **The sponsor authorizes nothing.** A relayed transaction whose authorization entries are not the wallet's own
  address credentials — in particular source-account credentials, which would spend the sponsor's own authority —
  is refused. The sponsor only sources and signs the envelope.
- **Blast radius.** The sponsor holds only what it needs for fees; it is not an arbiter, not an escrow party and
  cannot move escrowed funds. Losing the key costs its balance, not anyone's reward.

### Passkey wallet recovery

A passkey smart wallet's only signer is the WebAuthn credential created on the user's device. Consequences,
stated plainly rather than engineered around:

- **A lost passkey is a lost wallet.** With a platform authenticator whose credentials are not synced (no iCloud
  Keychain / Google Password Manager), losing the device loses the ability to authorize that wallet, and with it
  any balance left in it. BountyFlow cannot recover it: it holds no key of that wallet and the contract has no
  admin. The UI therefore presents passkey wallets as a working wallet, not a vault.
- **Recovery path.** The wallet contract supports several signers (`add_secp256r1`, `add_signer` with an Ed25519
  key or a policy contract). This deployment does not add one automatically — a second signer the platform chose
  would be a platform key over a user's funds — so the documented recovery is: keep the passkey in a synced
  keychain, or move the balance to an account wallet. Adding a user-chosen recovery signer is the natural next
  step, and the kit already builds those transactions.
- **Fresh device.** `GET /wallets/passkey/candidates` returns only the caller's own wallet's birth claims
  (creation transaction, ledger and WASM hash); passkey-kit still verifies every claim against RPC and asks for
  a fresh assertion before connecting, so the endpoint cannot be used to point a passkey at someone else's
  wallet. A wallet another account already owns is refused (409).
- **Deployment integrity.** BountyFlow re-derives the contract address from the credential id and refuses any
  deployment that is not exactly the expected contract from the configured WASM with the registered passkey as
  its signer, and marks the wallet `FAILED` if the deployed code does not read back as expected. The shared
  passkey-kit deployer is a published keypair by design; it only salts and authorizes the deployment and can
  never control the wallet.
- **User verification.** The wallet contract requires the WebAuthn User Present flag, not User Verified, so it
  stays compatible with authenticators without biometrics. A stolen, unlocked device can therefore authorize the
  wallet.

## Transaction verification pipeline

Every chain action follows **prepare → sign → submit → verify** (`app/modules/payments/service.py`):

| Step | Checks |
|---|---|
| Prepare | Permission, ownership and domain state. The signing wallet must be a verified wallet of the caller (except `RESOLVE_DISPUTE`, which must equal the escrow's arbiter). The escrow is read from chain and **its authenticity is verified** (below). Amounts come from the bounty (`reward × positions`; a partial deposit may only be ≤ the remaining amount), and payout destinations are the contributor's address locked on-chain by `ASSIGN`, else their current verified wallet. The call is simulated; the unsigned XDR, its hash and the arguments are stored on a `bountyflow_blockchain_transactions` row. |
| Sign | In the browser wallet. The server never holds user keys. |
| Submit | Only the row's creator. The tx must be `SIGNATURE_REQUIRED` and not expired. It must have been prepared for the configured network (SEC-08). The envelope must decode for the configured passphrase, its hash must equal the prepared hash (signatures do not change it, so any modified transaction is refused), its source must be the prepared source, and it must carry a valid ed25519 signature from that source. The row is locked `FOR UPDATE`, so concurrent submits serialise and repeats are idempotent. |
| Verify | Worker, sweep job or client poll. Only a network `SUCCESS` is followed by reading the escrow back from the contract, and only an **authentic** escrow is applied. Payouts are confirmed only when the contract reports the contributor's assignment as `Paid`. |

### Escrow authenticity (SEC-01, SEC-02)

The contract is permissionless: anyone can call `create_escrow` at any `bounty_id` with any token (a worthless
one), any arbiter (their own account) and any deadline (one minute from now). The backend therefore trusts an
on-chain escrow **only if** its immutable terms (id, requester, token, arbiter, reward per position, positions,
deadline) equal the arguments of a `create_escrow` that BountyFlow itself prepared for that bounty
(`matches_prepared_creation`, `_escrow_is_authentic`). A foreign escrow is never reconciled into the database and
never used to settle funding, payouts or refunds. Admin reconcile answers 409 `escrow_unverified`.

Escrow ids are `sha256("bountyflow:bounty:" || uuid || 16 random bytes)`, stored in `bountyflow_bounty_escrows`, so
they cannot be predicted from the public bounty id. If a foreign escrow still occupies the id before BountyFlow ever
saw its own escrow (the id became visible after a prepare), the requester's next `FUND` moves the bounty to a fresh
id, so squatting gains nothing.

### Double-spend and duplicate-payout defences

- Database: `bountyflow_payment_records` is unique per submission and per (bounty, contributor), and
  `bountyflow_blockchain_transactions` is unique per (network, hash). The row lock on the transaction serialises
  submit/verify. `CHECK paid_out + refunded <= funded` holds on escrows.
- Contract: an address is paid at most once per escrow (`AlreadyPaid`, persistent storage that is archived but
  never deleted), positions are bounded, and all arithmetic is checked.
- Redis locks are best-effort and fail open. `test_double_submit_with_redis_down_settles_once` fires concurrent
  submits with Redis down and asserts a single network submission and a single payout.

## Escrow contract: trust assumptions and limitations

See `contracts/README.md` for the full interface.

- **Upgradeable by one admin (v2).** Every escrow function calls `require_auth` on the acting party, and no
  function sends funds to an arbitrary address. The v2 contract (`CBCXG46F…3M4C`) has an admin, set by the
  constructor, whose only power is `upgrade(new_wasm_hash)` (and handing the role over with `set_admin`, which the
  new admin co-signs). A malicious upgrade could move escrowed funds, so the admin key is the most sensitive key of
  a deployment: keep it offline in a hardware wallet or a multisig account, and treat every `contract_upgraded`
  event as a release. The v1 contract (`CDX6FN2M…4SFY4CY`) has no admin and cannot change.
- **Bounded, M-of-N arbiters.** Arbiters act only on `Disputed` escrows, and only on an `Assigned` contributor:
  pay them up to their open position (the rest returns to the requester) or remove the assignment. On v2 a
  resolution executes only when the escrow's threshold of arbiters approved exactly the same contributor and
  amount in the current dispute round; mainnet configuration refuses a threshold below 2.
- **Review window.** Work recorded on-chain (`submit_work`) can be claimed by the contributor once the escrow's
  review window (1 to 30 days; the Testnet deployment allows 60 s for tests) passes unanswered. Paying a
  submission clears its clock, so the same work cannot be paid and claimed. Refunds wait while recorded work is
  unanswered.
- **Refund gating.** The requester can refund from `AwaitingFunding`, or from `CancelRequested` when nobody is
  assigned-but-unpaid or once the deadline has passed. Contributors are protected only by an on-chain
  assignment and by disputing before the deadline. BountyFlow sets `deadline = completion_deadline + 7 days`
  (or 60 days).
- **Checked arithmetic** (`checked_*` plus `overflow-checks = true` in release). `positions ≤ 100`, so
  `reward × positions` is checked with `checked_mul`.
- **Storage.** Persistent entries with TTL extension on every write or state-changing read. Expired entries are
  archived, not deleted, so funds and `Paid` markers survive and can be restored by anyone.
- **Re-entrancy.** Soroban forbids contract re-entry. The source now also persists state before token
  transfers (SEC-12).
- **Fixed and redeployed.** SEC-05 (a dispute with nobody assigned froze the escrow forever) and SEC-06
  (assignment after the deadline) are enforced by the current Testnet contract `CDX6FN2M…4SFY4CY`. The backend
  enforces the same guards for everything it prepares. The earlier contract `CCJ52FHV…LMXK` is superseded.
- **Arbiter liveness.** Disputed escrows only move when enough arbiters sign. Protect the arbiter keys and keep
  the threshold below the set size (2 of 3 on Testnet).
- **Token.** The contract accepts any SEP-41 token. BountyFlow's authenticity check restricts trusted escrows to
  the configured native XLM SAC.

## Input handling

- **Body size:** 1 MiB (`MAX_REQUEST_BODY_BYTES`), checked on both `Content-Length` and the streamed size (413).
- **Validation:** Pydantic schemas on every body and query. Money is decimal strings only (floats rejected),
  at most 7 decimals, positive and bounded. Usernames match `[a-z0-9_-]{3,30}` with reserved names blocked.
  Tag lists are normalised and bounded.
- **URLs:** every URL field (`avatar_url`, `github_url`, `portfolio_url`, `repository_url`, bounty `links`,
  `work_samples`, `evidence_url`, `evidence_links`, dispute evidence `url`) is `UrlStr`, which is http/https only
  and at most 500 characters. `javascript:`, `data:`, `vbscript:`, `file:` and `ftp:` are rejected
  (`test_every_url_field_rejects_non_http_schemes`).
- **Markdown** is stored raw and never rendered to HTML by the server. The SPA renders it without raw HTML.
  Emails are rendered with Jinja2 autoescaping, and notification titles (which become the email subject) are
  static strings, so no user text reaches mail headers.
  - This now covers **user-to-user** text as well (bounty Q&A). `SafeMarkdown` is the only renderer: it is
    lazy-loaded, passes `skipHtml` to react-markdown (so raw HTML is never parsed) and runs `rehype-sanitize`
    with a schema that drops `img`, `input`, `iframe`, `video` and `audio` and allows only `http`, `https` and
    `mailto` in `href`. Links open with `rel="noopener noreferrer nofollow"`, and images are rendered as links
    so a post cannot embed a tracking pixel. Q&A bodies are capped at 5,000 characters and stripped of NUL
    bytes before they reach PostgreSQL.
- **SQL:** ORM and bound parameters only. The only `text()` calls are constant (`SELECT 1`, advisory locks).
  Free-text search escapes LIKE wildcards (SEC-07). The full-text search uses `websearch_to_tsquery`.
- **JSONB:** `bountyflow_bounties.metadata` only holds validated `links` and server-set keys. Transaction and
  notification metadata is server-generated.
- **Trace headers:** `X-Request-ID` / `X-Correlation-ID` are accepted only if they match
  `[A-Za-z0-9._:-]{8,64}`; otherwise they are replaced (SEC-11).

## Rate limits and client IP

Redis fixed-window limits (`app/core/rate_limit.py`). They fail **open** when Redis is down and log
`rate_limit_unavailable`, which you should alert on.

| Scope | Limit | Key |
|---|---|---|
| `auth:register` | 10 / hour | IP |
| `auth:login:ip` / `auth:login:email` | 30 / 5 min, 10 / 5 min | IP, email |
| `auth:forgot` / `auth:forgot:email` | 10 / 15 min, 3 / 15 min | IP, email |
| `auth:reset` | 10 / 15 min | IP |
| `auth:verify` | 30 / 5 min | IP |
| `auth:resend` | 3 / 15 min | user |
| `auth:refresh` | 120 / 5 min | IP |
| `wallet:challenge`, `wallet:verify` | 20 / 5 min each | user |
| `bounty:create` / `bounty:report` | 30 / hour, 20 / hour | IP |
| `application:create` / `submission:create` / `dispute:create` | 60, 30, 10 / hour | IP |
| `chain:prepare` / `chain:submit` | 60 / 5 min each | IP |
| `chain:poll` (`GET /transactions/{ref}`) | 240 / min | IP |
| `feedback:submit` | 5 / hour | IP |
| `qa:post` / `qa:post:user` | 60 / hour (IP), 20 / 10 min (user) | IP, user |
| `qa:vote` / `qa:report` | 120 / hour (user), 20 / hour (IP) | user, IP |
| `github:challenge` / `github:verify` / `github:oauth` | 10, 20, 10 per 15 min | user |
| `github:recheck` / `github:link-pr` / `github:webhook` | 20 / 5 min (user), 60 / hour (IP), 600 / min (IP) | user, IP |

**Client IP (SEC-03).** Proxies append to `X-Forwarded-For`, so only the right-most `TRUSTED_PROXY_HOPS` entries
are trustworthy. The default is `1`, which fits the bundled nginx (`$proxy_add_x_forwarded_for`). Set `0` when
the API is reachable directly; `X-Forwarded-For` is then ignored. Also drop uvicorn's
`--forwarded-allow-ips *` in that setup. The value is truncated to 64 characters.


## GitHub account proof and webhook

BountyFlow reads only **public** data from the GitHub REST API and never writes to GitHub. Full rules in
[github.md](github.md).

### Gist proof (no OAuth secrets needed)

1. `POST /github/account/challenge {login}` mints `bountyflow:<username>:<16 random bytes>` and stores it in
   Redis for 30 minutes **keyed by the signed-in user's id**, together with the login being claimed. The
   challenge is therefore bound to one account and one GitHub username.
2. The user publishes it in a public gist. `POST /github/account/verify-gist` fetches that gist through the API
   and links the account **only if** the gist's owner login equals the claimed login *and* a file contains the
   exact challenge. Anonymous gists (no owner) never prove anything.
3. The challenge is deleted on success, so a gist cannot be replayed, and both endpoints are rate limited per
   user (10 and 20 per 15 minutes). If Redis is unavailable, linking fails **closed** (503).
4. The verified **numeric GitHub id** is stored, not just the login, so renaming the GitHub account (or someone
   else later taking that username) cannot silently re-point an established link. A unique constraint on
   `bountyflow_github_accounts.github_id` means one GitHub account maps to at most one BountyFlow account.
5. Gist responses are never cached — the user creates the gist moments before the check.

OAuth is optional and only offered when both `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` are set. Its `state`
is single-use, bound to the user in Redis and consumed with `GETDEL` even when the exchange then fails. The
access token is used once, server-side, to read `/user` and is never stored or logged.

### Webhook

`POST /api/v1/github/webhook` is off (404) unless `GITHUB_WEBHOOK_SECRET` is set. Every delivery must carry
`X-Hub-Signature-256` = `sha256=` + HMAC-SHA256 of the **raw** body with that secret, compared with
`hmac.compare_digest`; anything else is 401 `invalid_signature`. It is CSRF-exempt because GitHub signs each
delivery instead of carrying a cookie, and it is matched exactly in the exempt list like the other exemptions.

The payload is **never trusted for state**: it is only used to mark matching pull request rows as due, and the
actual state is then read from the REST API. `X-GitHub-Delivery` is remembered in Redis for 24 hours so a
redelivery does not re-queue work, unknown event types are ignored, and the endpoint is rate limited
(600 / minute).

### Reading GitHub safely

- `GITHUB_TOKEN` is optional, server-side only and sent to the configured API host only. It needs no repository
  or account permissions.
- A pull request URL is parsed strictly (host `github.com`, `/{owner}/{repo}/pull/{number}`, no credentials in
  the URL) before it is stored, and it is canonicalised, so a submission cannot be used to make the server
  fetch an arbitrary address.
- Responses are size-bounded when cached (gist file contents are truncated at 100,000 characters), and every
  GitHub call runs outside database transactions, so a slow or hostile response cannot hold row locks.
- When the rate limit is exhausted, a shared Redis backoff stops every caller until the reset instead of
  hammering GitHub.

## Bounty Q&A

- Posting needs an active account with a **verified email**; reading is public but follows the bounty's
  visibility (a draft or moderator-hidden bounty returns 404 to everyone else).
- Posting is rate limited per user (20 per 10 minutes) as well as per IP (60 per hour), with separate limits for
  votes (120 / hour) and reports (20 / hour).
- Authors edit and delete only their own posts; deletion is soft (the body is cleared and the author hidden) so
  a thread keeps its shape and a report still points at something.
- Moderators (`bounty:moderate`) hide and unhide posts with a reason. A hidden post's body is returned only to
  its author and to moderators, hiding marks the post's open reports as actioned, and every moderation step is
  written to the append-only audit log (`qa.post_hidden` / `qa.post_unhidden`).
- Only the bounty's requester can accept an answer or pin a question; the accepted answer is enforced one per
  question by a partial unique index, not only in application code.

## Feedback form

- **Open to visitors.** `POST /feedback` takes a note from anyone, signed in or not, and is still covered by the
  double-submit CSRF check rather than being added to the exempt list. Signing in mints the `bf_csrf` cookie;
  a visitor who never signs in is minted one by the first safe request they make (`CSRFMiddleware`), so the
  check works for them too.
- **Rate limit: 5 per hour per IP** (`feedback:submit`). Someone writing in good faith sends one note; the
  spare four cover a second thought and a retry after a failed request, and a script is held to 120 rows a day
  from one address. Nothing is emailed on arrival, so the only cost of abuse is rows in one table — which is
  also why a tighter limit is not worth turning away colleagues behind a shared office address.
- **No mail on submission.** One person reads the queue, so a message per submission would turn an anonymous
  form into a way to flood their inbox. The row *is* the delivery; staff read it in the admin console.
- **What is captured, and said so in the form:** the route the sender was on, the size of their window, and the
  `User-Agent` of the request. The form states all three before it is sent.
- **What is deliberately not captured:** nothing is read out of the page — no field values, no wallet address,
  no session or CSRF token, no session id. The route is stored without its query string or fragment (the API
  cuts them off rather than trusting the client not to send them), because a marketplace search or an
  unsubscribe token can live there. The `User-Agent` comes from the request header, never from a body field, and
  the **client IP is not stored**: the rate limiter keeps it in a Redis key for an hour and nothing writes it to
  the database.
- **Email.** A signed-out sender may leave an address to be written back to; it is validated and kept as they
  typed it. A signed-in sender's account is the reply address, and an address sent in the body is discarded.
- **Reading it** needs `feedback:review` (moderators and admins). The queue holds addresses and user agents of
  people who are not signed in, which is why it is its own permission rather than folded into `report:review`.
  Marking a note handled — or putting it back — is written to the append-only audit log (`feedback.handled` /
  `feedback.reopened`).

## Transport, headers and CORS

- API responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `Content-Security-Policy: default-src 'none'` (outside
  the docs UI), `Cache-Control: no-store` on `/api/*`, and HSTS when `COOKIE_SECURE=true`. nginx adds the SPA
  CSP.
- CORS is an explicit allowlist with credentials. `*` is refused at startup (SEC-09) because Starlette reflects
  any origin when credentials are enabled. Allowed headers are limited to `Content-Type`, `X-CSRF-Token` and
  the trace headers.
- Errors use one envelope. Unhandled exceptions return a generic 500 with a request id and log the stack trace
  server-side only. Validation errors echo field names and messages, never input values.
- Containers run as uid 10001 with `APP_ENV=production` by default (so the production validator applies), and
  docker-compose binds every port to `127.0.0.1`.

## Secrets management

- All secrets come from the environment (`.env`, gitignored and excluded from Docker build contexts).
  `.env.example` holds placeholders only.
- In `staging`/`production` the API refuses to start with a short or placeholder `JWT_SECRET`,
  `COOKIE_SECURE=false`, a missing `SOROBAN_CONTRACT_ID`, or a missing
  `WALLET_CHALLENGE_SIGNING_SECRET`. CORS `*` and non-HMAC JWT algorithms are refused in every environment.
- Stellar secret keys (deployer, arbiter) stay in the Stellar CLI key store and are never in the repository. The
  wallet-challenge key never holds funds and signs nothing that is submitted.
- Only hashes of refresh, verification and reset tokens are stored.

## Logging and redaction

- Structured logs redact sensitive field names (`password`, `token`, `access_token`, `refresh_token`,
  `authorization`, `cookie`, `secret`, `private_key`, `seed`, `jwt_secret`, `smtp_password`, `signed_xdr`,
  `signed_challenge_xdr`, `csrf_token`, …) before any handler sees them, on top of Logifyx message masking.
- Email bodies (which contain single-use links) are never logged. Logs carry the template, subject and
  recipient only.
- A review of every logger call found no token, password, XDR or cookie values being logged.
- The access log records method, path, status and duration. Paths never contain secrets (tokens travel in JSON
  bodies).
- Alert on `refresh_token_reuse_detected`, `foreign_escrow_detected`, `escrow_id_rotated`,
  `confirmed_transaction_on_foreign_escrow`, `payout_not_reflected_on_chain`, `rate_limit_unavailable`.

## Dependency scanning

| Tool | Scope | Result (2026-09-26) |
|---|---|---|
| `pip-audit` (`uv export --frozen --no-dev` → `uvx pip-audit -r … --no-deps`) | Backend runtime dependencies (locked) | No known vulnerabilities |
| `cargo audit` 0.22.2 | `contracts/Cargo.lock` (215 crates) | No vulnerabilities. One informational warning: `paste` 1.0.15 is unmaintained (RUSTSEC-2024-0436), pulled in transitively by `soroban-sdk`, with no known exploit. |

Run both in CI on every lockfile change.

## Review findings (2026-09-26)

Baseline: the initial backend, contract and infrastructure commit. "Fixed" means the change is in the tree and a
regression test is in `backend/tests/integration/security/` or `contracts/bounty_escrow/src/test.rs`.

| ID | Severity | Title | Location | Status | Test |
|---|---|---|---|---|---|
| SEC-01 | High | The backend adopted any on-chain escrow at a bounty's id, never checking token, arbiter, deadline or requester. A requester could "fund" with a worthless token, then get payouts recorded as confirmed XLM, name their own arbiter, or set a one-minute deadline. | `app/modules/payments/service.py` (`_sync_escrow_from_chain`, `_on_success`, `reconcile_bounty`); `app/blockchain/reconciliation.py` | Fixed | `test_foreign_token_escrow_is_never_adopted`, `test_reconcile_refuses_unverified_escrow` |
| SEC-02 | Medium | Escrow id was `sha256(public bounty UUID)`. Anyone could pre-create a bounty's escrow and block its funding permanently. | `app/blockchain/soroban.py` (`onchain_bounty_id`); `payments/service.py` (`_get_or_create_escrow`, `_recover_from_foreign_escrow`) | Fixed | `test_squatted_escrow_id_does_not_block_funding` |
| SEC-03 | Medium | Rate limits keyed on the left-most, client-controlled `X-Forwarded-For` entry, so rotating it bypassed every IP limit (login brute force, registration spam). An oversized value caused a 500 on login and registration (`VARCHAR(64)`). | `app/core/rate_limit.py` (`client_ip`) | Fixed | `test_spoofed_forwarded_for_cannot_bypass_ip_rate_limit`, `test_oversized_forwarded_for_does_not_break_login` |
| SEC-04 | Medium | Argon2id (~100 ms) ran on the event loop, so unauthenticated login and register traffic stalled all requests (cheap DoS). | `app/modules/auth/service.py`, `app/core/security.py` | Fixed | `test_password_hashing_runs_off_the_event_loop` |
| SEC-05 | Medium | An on-chain dispute could be raised with no on-chain-assigned contributor. The contract has no exit from `Disputed` in that case, so the escrow was frozen forever. | `contracts/bounty_escrow/src/lib.rs` (`raise_dispute`); `payments/service.py` (RAISE_DISPUTE plan) | Fixed. Backend guard landed concurrently by the bug-scan engineer; contract source fixed (**redeploy required**). | `test_onchain_dispute_requires_onchain_assignment`; `dispute_requires_an_assigned_contributor` |
| SEC-06 | Low | An on-chain assignment after the deadline gave the contributor no protection (the requester can refund immediately) while looking like protection. | `lib.rs` (`assign`); `payments/service.py` (ASSIGN plan) | Fixed (contract: **redeploy required**) | `test_onchain_assignment_after_deadline_is_refused`; `assign_rejected_at_or_after_deadline` |
| SEC-07 | Low | LIKE wildcards (`%`, `_`) in search were not escaped (match-everything or pathological patterns). | `app/modules/bounties/repository.py`, `app/modules/admin/router.py` | Fixed | `test_marketplace_search_escapes_like_wildcards` |
| SEC-08 | Low | A transaction prepared for one network could be submitted after the deployment switched networks (originally: a development marker's acceptance depended on a row flag). The development marker no longer exists. | `payments/service.py` (`submit_transaction`) | Fixed | `test_transaction_prepared_for_another_network_cannot_be_submitted`, `test_non_signatures_are_rejected_as_wallet_proofs`, `test_signed_envelope_pipeline_cannot_be_bypassed` |
| SEC-09 | Low | `CORS_ORIGINS=*` was accepted although credentials are enabled, and Starlette then reflects any origin. | `app/core/config.py` | Fixed | `test_production_configuration_is_validated` |
| SEC-10 | Low | `JWT_ALGORITHM` accepted any string (`none`, `RS256`…). | `app/core/config.py` | Fixed | `test_jwt_algorithm_is_pinned_to_hmac` |
| SEC-11 | Low | `X-Correlation-ID` (and loosely `X-Request-ID`) was propagated unvalidated into logs, audit rows and every outbox event (log forging, unbounded size). | `app/core/middleware.py` | Fixed | `test_client_trace_ids_are_sanitised` |
| SEC-12 | Info | The contract transferred tokens before persisting escrow state. Not exploitable, because Soroban blocks re-entry. | `lib.rs` (`release`, `resolve_dispute`) | Fixed in source (redeploy) | `payouts_record_state_and_move_funds_once` |
| SEC-13 | Info | CSRF exemption matched by path suffix and only under `/api/v1`, which is fragile. | `app/core/middleware.py` | Fixed | `test_every_mutating_route_requires_csrf` |
| SEC-14 | Low | Registration reveals whether an email is registered (409). | `app/modules/auth/service.py` | Accepted risk (UX; rate-limited). Forgot-password is generic. | — |
| SEC-15 | Info | The CSRF token is not bound to the session (plain double-submit), which is vulnerable to cookie tossing from a sibling domain. | `app/core/middleware.py` | Documented | — |
| SEC-16 | Info | `GET /transactions/{ref}` shows submitted transactions of hidden bounties and lets anonymous users trigger RPC verification (rate-limited). | `payments/service.py` (`get_transaction`) | Accepted risk (on-chain data is public) | — |
| SEC-17 | Info | `/users/{u}/contributions` lists `UNLISTED` bounties. | `app/modules/users/router.py` | Documented | — |
| SEC-18 | Info | Concurrent refreshes from two tabs trip reuse detection and end the session (fails safe). | `app/modules/auth/service.py` | Documented | — |
| SEC-19 | Info | Rate limiter and transaction locks fail open without Redis. The DB and contract still prevent double effects (tested). | `app/core/rate_limit.py`, `payments/service.py` | Documented | `test_double_submit_with_redis_down_settles_once`, `test_wallet_challenges_fail_closed_without_redis` |

Defences confirmed and locked in by tests (no finding): CSRF on every mutating route, authentication on every
non-public route, staff-only routes, the IDOR matrix, role escalation, suspension, refresh-token binding,
wallet-challenge binding, single use and uniqueness, the envelope pipeline (hash, source, signature, passphrase,
another user's transaction), non-signature markers rejected, server-side amounts, URL schemes,
body limit, JSON-only login, and the production configuration validator.

## Known limitations and recommendations for mainnet

1. **Redeploy the escrow contract** with the SEC-05/06/12 fixes before relying on it for anything beyond
   Testnet, then get an independent audit. Use a multisig or hardware-wallet arbiter, and document arbiter key
   rotation (existing escrows keep their arbiter).
2. **Contract-level escrow binding.** Consider a contract version that binds the escrow id to the requester
   (for example, a key of `(requester, bounty_id)`) or allowlists the token at deployment, so integrity does not
   depend on off-chain checks alone.
3. **CSRF hardening:** use HMAC-signed double-submit tokens bound to the session id, and `__Host-` cookie
   prefixes (`__Host-bf_csrf`, `__Host-bf_access`), or `SameSite=Strict` if the product allows it.
4. **Proxy configuration:** set `TRUSTED_PROXY_HOPS` to match the real topology (add it to `.env.example`), and
   drop `--forwarded-allow-ips *` where the API is not only reachable through the proxy.
5. **Distributed rate limiting that fails closed** for authentication endpoints (or a WAF in front), plus
   per-account lockout with exponential backoff, and a breached-password check (k-anonymity HIBP) at
   registration and reset.
6. **Disable `/api/docs` and `/api/openapi.json`** in production, or put them behind staff authentication.
7. **Monitoring:** alert on the log events listed above. Reconcile escrows periodically, not only after
   transactions.
8. **Supply chain:** run `pip-audit` and `cargo audit` in CI. Pin container base images by digest. Generate
   SBOMs.
9. **Privacy:** notification emails log recipient addresses. Consider hashing them in production logs.
10. **Session UX:** add a short grace window for concurrent refreshes (SEC-18) so multi-tab use does not end
    sessions.
