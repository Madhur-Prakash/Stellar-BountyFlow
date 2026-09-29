# BountyFlow REST API

Base path: `/api/v1`. Interactive OpenAPI docs are served by the API at `/api/docs` (Swagger UI) and `/api/openapi.json`.

This document is the contract between the frontend, backend, and workers. All shapes below are JSON.

## Conventions

### Authentication (cookie-based)

| Cookie        | HttpOnly | Path                  | Purpose                                              |
|---------------|----------|-----------------------|------------------------------------------------------|
| `bf_access`   | yes      | `/`                   | Short-lived JWT access token (default 15 minutes)    |
| `bf_refresh`  | yes      | `/api/v1/auth`        | Opaque rotating refresh token (default 30 days)      |
| `bf_csrf`     | **no**   | `/`                   | CSRF double-submit token, readable by JS             |

- The browser always sends requests with `credentials: "include"`.
- Every **mutating** request (`POST`, `PATCH`, `PUT`, `DELETE`) must send header `X-CSRF-Token: <value of bf_csrf cookie>`. Exempt: `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/verify-email` (these either establish the session or are token-protected).
- On `401` with error code `token_expired` or `not_authenticated`, the client calls `POST /auth/refresh` once, then retries the original request. If refresh fails, the user is logged out.
- The refresh token is rotated on every refresh. Reuse of a revoked refresh token revokes the whole session family.

### Errors

Every error uses this envelope:

```json
{ "error": { "code": "validation_error", "message": "Human readable message", "details": [ ... ], "request_id": "..." } }
```

Common codes: `validation_error` (422), `not_authenticated` (401), `token_expired` (401), `forbidden` (403), `csrf_failed` (403), `not_found` (404), `conflict` (409), `invalid_state_transition` (409), `escrow_unverified` (409, the on-chain escrow at the bounty's escrow id was not prepared by BountyFlow; see docs/security.md), `rate_limited` (429), `blockchain_error` (502), `internal_error` (500).

`validation_error.details` is a list of `{ "field": "title", "message": "..." }`.

`details` is optional (omitted when there is nothing to add) and is not always a list for other codes. Additional codes the backend returns:

| Code | Status | Meaning |
|------|--------|---------|
| `email_not_verified` | 403 | Publishing requires a verified email |
| `wallet_not_verified` | 403 | The `wallet_address` is not a verified wallet of the caller |
| `contract_rejected` | 422 | The escrow contract rejected the action during RPC preflight simulation; `details.contract_error` is the contract error name (e.g. `AssignmentsOutstanding`, `AlreadyPaid`) |
| `wrong_wallet` | 422 | Sign with the wallet recorded on the escrow / on-chain assignment |
| `account_not_found` | 422 | The wallet account does not exist on the network yet |
| `contributor_wallet_missing` | 422 | The contributor has no verified wallet to receive the reward |
| `trustline_missing` | 422 | The receiving (or funding) wallet has no trustline for the reward asset. `details` carries `asset`, `address`, `state` and `stage` (`funding`, `assignment`, `payout`, `batch_payout`, `refund`) |
| `trustline_unauthorized` | 422 | A trustline exists but the issuer has not authorized it |
| `insufficient_balance` | 422 | The funding wallet holds less of the asset than the deposit needs |
| `asset_not_supported` | 422 | The reward asset is not an enabled registry asset on this network |
| `trustline_exists` / `trustline_not_required` | 409 / 422 | The wallet already has the trustline; or the asset needs none (XLM, or a `C…` contract wallet) |
| `signature_invalid` | 422 | The signed envelope does not match the prepared transaction |
| `service_unavailable` | 503 | A required component (e.g. escrow configuration, Redis for wallet challenges) is unavailable |
| `method_not_allowed` / `payload_too_large` | 405 / 413 | Standard HTTP errors in the same envelope |

### Pagination

List endpoints accept `page` (1-based, default 1) and `page_size` (default 20, max 100) and return:

```ts
type Page<T> = { items: T[]; total: number; page: number; page_size: number; pages: number }
```

### Money

- Monetary amounts are **decimal strings** with up to 7 fractional digits (Stellar precision), e.g. `"250.5000000"`. Never floats.
- `reward_amount` on a bounty is the reward **per position**. Required escrow = `reward_amount × positions_available`.
- Every amount carries its **asset**. `identifier` is `"native"` (XLM) or `"CODE:ISSUER"`; `contract_id` is the
  asset's Stellar Asset Contract on the active network (derived by the backend, never sent by a client):

```ts
type Asset = {
  code: string; issuer: string | null
  type: "native" | "credit_alphanum4" | "credit_alphanum12"
  contract_id: string | null; identifier: string; decimals: number
}
type AssetAmount = { asset: Asset; amount: DecimalString }
```

- **Amounts of different assets are never added together.** Where a total could span assets, the scalar field
  stays XLM-only (unchanged for existing clients) and a `*_by_asset: AssetAmount[]` field beside it carries
  every asset: `PublicStats.payout_volume_by_asset`, `UserStats.rewards_received_by_asset` /
  `rewards_paid_by_asset`, `RequesterAnalytics.escrowed_by_asset` / `paid_by_asset` / `spending_by_asset`,
  `ContributorAnalytics.earned_by_asset` / `earnings_by_asset`, `PlatformAnalytics.transactions.payout_volume_by_asset`
  and `PlatformDay.payout_volume_by_asset`.

### Timestamps

ISO 8601 with timezone (UTC), e.g. `"2026-09-25T12:00:00Z"`.

## Enums

```ts
type Role = "USER" | "MODERATOR" | "ADMIN"
type BountyStatus = "DRAFT" | "OPEN" | "FUNDING_PENDING" | "FUNDED" | "IN_PROGRESS" | "UNDER_REVIEW"
  | "COMPLETED" | "CANCEL_REQUESTED" | "CANCELLED" | "DISPUTED" | "EXPIRED"
type FundingStatus = "UNFUNDED" | "PENDING" | "PARTIALLY_FUNDED" | "FUNDED" | "REFUND_PENDING" | "REFUNDED" | "SETTLED"
type Category = "DEVELOPMENT" | "BUG_BOUNTY" | "DESIGN" | "SECURITY" | "DOCUMENTATION" | "RESEARCH" | "COMMUNITY" | "OTHER"
type Difficulty = "BEGINNER" | "INTERMEDIATE" | "ADVANCED" | "EXPERT"
type Visibility = "PUBLIC" | "UNLISTED"
type ApplicationStatus = "PENDING" | "ACCEPTED" | "REJECTED" | "WITHDRAWN"
type SubmissionStatus = "SUBMITTED" | "REVISION_REQUESTED" | "RESUBMITTED" | "APPROVED" | "REJECTED"
type PaymentStatus = "NOT_REQUIRED" | "CREATED" | "SIGNATURE_REQUIRED" | "SUBMITTED" | "CONFIRMED" | "FAILED" | "REFUND_PENDING" | "REFUNDED"
type TxStatus = "CREATED" | "SIGNATURE_REQUIRED" | "SUBMITTED" | "CONFIRMED" | "FAILED" | "EXPIRED"
type TxType = "ESCROW_CREATE" | "ESCROW_FUND" | "ASSIGN" | "PAYOUT" | "CANCEL_REQUEST" | "CANCEL_CONSENT"
  | "REFUND" | "DISPUTE_RAISE" | "DISPUTE_RESOLVE" | "WALLET_CHALLENGE"
  | "MILESTONE_PAYOUT" | "BATCH_PAYOUT" | "SUBMIT_WORK" | "REQUEST_CHANGES" | "REJECT_SUBMISSION" | "CLAIM" | "DISPUTE_VOTE"  // escrow v2
type ChainAction = "FUND" | "ASSIGN" | "PAYOUT" | "REQUEST_CANCEL" | "CONSENT_CANCEL" | "REFUND" | "RAISE_DISPUTE" | "RESOLVE_DISPUTE"
  | "MILESTONE_PAYOUT" | "BATCH_PAYOUT" | "SUBMIT_WORK" | "REQUEST_CHANGES" | "REJECT_SUBMISSION" | "CLAIM" | "DISPUTE_VOTE"  // escrow v2
type DisputeStatus = "OPEN" | "UNDER_REVIEW" | "RESOLVED" | "DISMISSED"
type DisputeResolution = "RELEASE_TO_CONTRIBUTOR" | "REFUND_TO_REQUESTER" | "SPLIT" | "DISMISSED"   // SPLIT: v2 escrows
type ReportStatus = "OPEN" | "REVIEWING" | "ACTIONED" | "DISMISSED"
type NotificationType = "BOUNTY_PUBLISHED" | "BOUNTY_FUNDED" | "APPLICATION_RECEIVED" | "APPLICATION_ACCEPTED"
  | "APPLICATION_REJECTED" | "SUBMISSION_RECEIVED" | "REVISION_REQUESTED" | "SUBMISSION_APPROVED"
  | "SUBMISSION_REJECTED" | "PAYMENT_CONFIRMED" | "BOUNTY_CANCELLED" | "BOUNTY_EXPIRED" | "DISPUTE_UPDATE" | "SYSTEM"
  | "SAVED_SEARCH_MATCH"   // a new bounty, or a digest of them, matches a saved search
```

## Shared shapes

```ts
type UserSummary = { id: string; username: string; display_name: string; avatar_url: string | null }

type Me = {
  id: string; email: string; email_verified: boolean; username: string; display_name: string
  avatar_url: string | null; bio: string | null; role: Role
  skills: string[]; interests: string[]; github_url: string | null; portfolio_url: string | null
  wants_to_request: boolean; wants_to_contribute: boolean
  onboarding: { email_verified: boolean; profile_completed: boolean; role_selected: boolean; wallet_connected: boolean; first_action_taken: boolean; completed: boolean }
  created_at: string
}

type Wallet = { id: string; public_address: string; network: string; verification_status: "VERIFIED"; verified_at: string; created_at: string }

type UserStats = {
  bounties_created: number; bounties_completed_as_requester: number
  contributions_completed: number; applications_submitted: number
  acceptance_rate: number | null  // 0..1, accepted / decided applications
  approval_rate: number | null    // 0..1, approved / reviewed submissions
  total_rewards_received: string  // XLM, payouts CONFIRMED on-chain
  total_rewards_paid: string
}

type PublicProfile = {
  id: string; username: string; display_name: string; avatar_url: string | null; bio: string | null
  skills: string[]; interests: string[]; github_url: string | null; portfolio_url: string | null
  joined_at: string; wallets: { public_address: string; network: string; verified_at: string }[]
  stats: UserStats
}

type EscrowView = {
  contract_id: string | null; network: string; asset: Asset; onchain_bounty_id: string
  required_amount: string; funded_amount: string; paid_out_amount: string; refunded_amount: string
  state: "NOT_CREATED" | "AWAITING_FUNDING" | "FUNDED" | "CANCEL_REQUESTED" | "DISPUTED" | "COMPLETED" | "CANCELLED"
  last_reconciled_at: string | null
}

type BountySummary = {
  id: string; slug: string; title: string; short_description: string
  category: Category; difficulty: Difficulty; tags: string[]; required_skills: string[]
  reward_amount: string; reward_asset: Asset; total_reward: string; network: string
  status: BountyStatus; funding_status: FundingStatus
  application_deadline: string | null; completion_deadline: string | null
  positions_available: number; positions_filled: number; applications_count: number
  requester: UserSummary; is_featured: boolean; is_bookmarked: boolean
  created_at: string; published_at: string | null
}

type BountyDetail = BountySummary & {
  description: string            // Markdown (render safely, no raw HTML)
  eligibility_criteria: string | null
  submission_requirements: string | null
  acceptance_criteria: string | null
  repository_url: string | null
  links: { label: string; url: string }[]
  visibility: Visibility
  escrow: EscrowView | null
  viewer: {
    is_owner: boolean; is_assigned: boolean; can_apply: boolean; can_submit: boolean
    application: { id: string; status: ApplicationStatus } | null
    assignment_id: string | null
  } | null   // null for anonymous viewers
}

type Application = {
  id: string; bounty_id: string; bounty: { id: string; slug: string; title: string; status: BountyStatus }
  contributor: UserSummary & { skills: string[] }
  cover_message: string; relevant_experience: string | null; work_samples: string[]
  status: ApplicationStatus; review_note: string | null   // review_note only visible to the bounty owner
  reviewed_at: string | null; created_at: string; updated_at: string
}

type Submission = {
  id: string; bounty_id: string; bounty: { id: string; slug: string; title: string; status: BountyStatus }
  contributor: UserSummary; assignment_id: string; version: number
  description: string; evidence_url: string | null; evidence_links: string[]
  status: SubmissionStatus; review_feedback: string | null
  reviewer: UserSummary | null; reviewed_at: string | null
  payment: PaymentRecord | null
  created_at: string; updated_at: string
}

type PaymentRecord = {
  id: string; bounty_id: string; contributor: UserSummary; submission_id: string
  amount: string; asset: Asset; payment_status: PaymentStatus
  transaction: BlockchainTransaction | null; created_at: string; settled_at: string | null
}

type BlockchainTransaction = {
  id: string; bounty_id: string | null; bounty_title: string | null; user: UserSummary | null
  transaction_hash: string | null; transaction_type: TxType; network: string
  amount: string | null; asset: Asset | null; status: TxStatus
  source_address: string | null; destination_address: string | null
  ledger_sequence: number | null; submitted_at: string | null; confirmed_at: string | null
  failure_reason: string | null; explorer_url: string | null
  created_at: string
}

type PreparedTransaction = {
  transaction: BlockchainTransaction   // status SIGNATURE_REQUIRED
  unsigned_xdr: string                 // base64 transaction envelope for the wallet to sign
  network_passphrase: string
  network: string
  summary: { action: ChainAction; description: string; amount: string | null; asset: Asset | null; fee_estimate_stroops: string | null; contract_id: string | null; function_name: string }
  expires_at: string
}

type ActivityItem = {
  id: string; action: string; actor: UserSummary | null; entity_type: string; entity_id: string
  bounty: { id: string; slug: string; title: string } | null
  metadata: Record<string, unknown>; created_at: string; link: string | null
}

type Notification = { id: string; notification_type: NotificationType; title: string; message: string; payload: Record<string, unknown>; link: string | null; read_at: string | null; created_at: string }

type Dispute = {
  id: string; bounty: { id: string; slug: string; title: string }; raised_by: UserSummary
  reason: string; status: DisputeStatus; assigned_moderator: UserSummary | null
  resolution: DisputeResolution | null; resolution_note: string | null
  evidence: { id: string; submitted_by: UserSummary; description: string; url: string | null; created_at: string }[]
  created_at: string; resolved_at: string | null
}
```

### Extensions to the shared shapes

The backend returns every field above. It also returns the following extra fields, which clients may rely on:

| Shape | Extra fields |
|-------|--------------|
| `Me` | `permissions: string[]` (RBAC permission names) |
| `EscrowView` | `explorer_url: string \| null` (contract explorer link) |
| `BountyDetail` | `is_hidden: boolean` (moderator-hidden; only owners/staff can see such bounties), `cancel_reason: string \| null`; `viewer.is_moderator: boolean` |
| `Application` | `assignment_id: string \| null` (set once the application was accepted), `onchain_assigned: boolean` (locked in the escrow via `ASSIGN`) |
| `Submission` | `revisions: { version: number; description: string; evidence_url: string \| null; evidence_links: string[]; created_at: string }[]` (filled on `GET /submissions/{id}` and review responses) |
| `PaymentRecord` | `bounty_title: string \| null`, `bounty_slug: string \| null` |
| `BlockchainTransaction` | `bounty_slug: string \| null`, `contract_id: string \| null`, `function_name: string \| null` |
| `Dispute` | `contributor: UserSummary \| null` (the assigned contributor the dispute concerns), `escrow_frozen_onchain: boolean`, `requires_onchain_execution: boolean` (a release/refund decision the arbiter must still execute with `RESOLVE_DISPUTE`) |
| `EscrowView` (v2) | `contract_version: number` (1 or 2, the contract this escrow lives on), `arbiter_addresses: string[]`, `arbiter_threshold: number`, `review_window_seconds: number \| null` |
| `BountyDetail` (v2) | `milestones: Milestone[]` (empty unless the reward is paid in milestones), `review_window_seconds: number \| null` |
| `Submission` (v2) | `milestone: { id, position, title, amount, status } \| null`, `onchain_review: OnchainReview \| null`, `can_record_onchain: boolean` (the viewer can sign `SUBMIT_WORK` for it) |
| `PaymentRecord` (v2) | `milestone_id: string \| null` |
| `Dispute` (v2) | `contract_version: number`, `arbiter_threshold: number`, `arbiter_approvals: number` (verified approvals of the current round), `contributor_amount: string \| null` (SPLIT); `requires_onchain_execution` is also true for a SPLIT on a frozen escrow |
| `GET /config/public` | `contract_explorer_url: string \| null` |
| `AdminUser` | `last_login_at: string \| null` |
| Admin report | `resolved_at: string \| null` |
| Admin audit log entry | `bounty_id: string \| null` |

### Lifecycle rules clients should know

- **Partially funded bounties** (`OPEN` + `PARTIALLY_FUNDED`) can be cancelled: `POST /bounties/{id}/cancel` moves them to `CANCEL_REQUESTED`, and the deposit is returned with chain action `REFUND` (no `REQUEST_CANCEL` needed while the escrow is still `AWAITING_FUNDING`). Unfunded bounties still go straight to `CANCELLED`.
- **Freezing the escrow** (`RAISE_DISPUTE`) is only possible when the disputed contributor is assigned on-chain (chain action `ASSIGN` confirmed); otherwise prepare returns `409 invalid_state_transition` and the dispute is resolved off-chain by a moderator. Submitting a prepared `RAISE_DISPUTE` after the dispute was closed returns `409` and the transaction becomes `EXPIRED`.
- A verified on-chain `RESOLVE_DISPUTE` also settles the disputed submission (`APPROVED` when paid, `REJECTED` when the claim is released). A dispute raised during a cancellation request returns the bounty to `CANCEL_REQUESTED` once resolved.
- `PATCH /bounties/{id}`: a new `application_deadline` / `completion_deadline` must be in the future (`422`).
- Chain prepare `amount` must be a positive decimal string with at most 7 fractional digits (`422` otherwise).
- `POST /transactions/{id}/submit` on a transaction whose earlier submission reached the network (e.g. the response was lost) records it as `SUBMITTED` and verifies it, even after `expires_at`, instead of failing it.
- Notifications for `BOUNTY_CANCELLED`, `BOUNTY_EXPIRED` and deadline reminders now also reach assigned contributors and waiting applicants (not only the requester).

## Endpoints

### Health (not versioned)
- `GET /health` → `{ status: "ok", service, version }`
- `GET /health/live` → `{ status: "ok" }`
- `GET /health/ready` → `{ status: "ok" | "degraded", checks: { database, redis, kafka, blockchain_rpc } }` (each `"ok" | "error" | "disabled"`)

### Config
- `GET /config/public` → `{ app_name, network, network_passphrase, horizon_url, soroban_rpc_url, explorer_base_url, contract_id, native_asset_contract_id, arbiter_address, blockchain_mode: "testnet" | "mainnet" }`

### Auth
- `POST /auth/register` `{ email, password, username, display_name }` → `201 Me` (sets cookies, sends verification email). Password: 10–128 chars.
- `POST /auth/login` `{ email, password }` → `Me` (sets cookies)
- `POST /auth/logout` → `204` (revokes session, clears cookies)
- `POST /auth/refresh` → `Me` (rotates cookies)
- `POST /auth/verify-email` `{ token }` → `Me` or `{ verified: true }`
- `POST /auth/resend-verification` → `204`
- `POST /auth/forgot-password` `{ email }` → `202 { message }` (always generic)
- `POST /auth/reset-password` `{ token, password }` → `204` (revokes all sessions)
- `GET /auth/me` → `Me`
- `GET /auth/sessions` → `{ id, created_at, last_used_at, user_agent, is_current }[]`
- `DELETE /auth/sessions/{session_id}` → `204`

### Users
- `GET /users/me` → `Me`
- `PATCH /users/me` `{ display_name?, username?, avatar_url?, bio?, skills?, interests?, github_url?, portfolio_url?, wants_to_request?, wants_to_contribute? }` → `Me`
- `POST /users/me/onboarding/complete` → `Me`
- `GET /users/{username}` → `PublicProfile`
- `GET /users/{username}/bounties?page&page_size` → `Page<BountySummary>` (public bounties created)
- `GET /users/{username}/contributions?page&page_size` → `Page<{ bounty: BountySummary; completed_at: string; amount: string | null; transaction_hash: string | null }>`
- `GET /users/{username}/stats` → `UserStats`
- `GET /users/{username}/reputation` → `ReputationSummary` (attested completions only; `earned` is per asset)
- `GET /users/{username}/attestations?page&page_size` → `Page<Attestation>` (completions recorded on-chain)

### Reputation and credentials
- `GET /attestations/{id|uuid}` → `Attestation & { chain }`. Public page for one completion; `chain` is a live
  read of the registry contract (`{ checked_at, found, matches, revoked, record, error }`), cached 30 s.
- `GET /reputation/me/attestations?page&page_size` → `Page<Attestation>` (the owner's, including in-flight ones)
- `GET /reputation/me/counts` → `{ confirmed, in_progress, revoked, failed }`
- `GET /credentials/issuer` → `{ enabled, did, verification_method, did_document_url, status_list_url, cryptosuite }`
- `GET /credentials/status/revocation` → signed `BitstringStatusListCredential` (`application/vc+json`, public)
- `POST /credentials/verify` `{ credential }` → `VerificationReport` (public, CSRF-exempt; see docs/credentials.md)
- `POST /credentials/completions/{attestation_id}` → `IssuedCredential` (the contributor; idempotent)
- `POST /credentials/summary` → `IssuedCredential` (every standing attested completion)
- `GET /credentials/me` → `CredentialRecord[]`; `GET /credentials/{id}` → `IssuedCredential`
- `GET /credentials/{id}/download` → the credential JSON as an attachment
- `GET /.well-known/did.json` → the issuer's DID document (unversioned, public)
- Staff: `GET /admin/attestations?status&page&page_size`, `POST /admin/attestations/backfill`,
  `POST /admin/attestations/reconcile`, `GET /admin/attestations/reconciliation`,
  `POST /admin/attestations/{id}/retry` (`system:health`), `POST /admin/attestations/{id}/revoke` `{ reason }`
  (`user:manage`)

```ts
// One completed (bounty, contributor) pair. `amount` is everything that contributor was paid on the bounty,
// in the bounty's reward asset, however many transfers paid it (`payments_count`).
type Attestation = {
  id: string; onchain_id: number | null
  status: "PENDING" | "SUBMITTED" | "CONFIRMED" | "REVOKING" | "REVOKED" | "FAILED"
  network: string; contributor: UserSummary; contributor_address: string   // G… or a passkey wallet C…
  bounty: { id: string; slug: string; title: string }
  amount: string; asset: Asset; payments_count: number
  first_paid_at: string | null; completed_at: string; attested_at: string | null; confirmed_at: string | null
  payout_tx_hash: string; payout_explorer_url: string | null
  attestation_tx_hash: string | null; attestation_explorer_url: string | null
  contract_id: string; contract_explorer_url: string
  escrow_contract_id: string; onchain_bounty_id: string; token_contract_id: string
  revoked_at: string | null; revocation_reason: string | null
}

type ReputationSummary = {
  enabled: boolean            // false when the registry is not configured on this server
  attested_completions: number; revoked: number
  earned: AssetAmount[]       // one total per asset; never summed across assets
  first_completed_at: string | null; last_completed_at: string | null
  network: string; contract_id: string | null; contract_explorer_url: string | null
  attester_address: string | null
}

type VerificationReport = {
  verified: boolean
  checks: { id: "format"|"issuer"|"signature"|"validity"|"status"|"attestation"
            label: string; status: "pass"|"fail"|"skip"; detail: string }[]
  credential_id: string | null; kind: "completion" | "summary" | null
  issuer: { id: string | null; name: string | null; is_this_site: boolean }
  subject: string | null; valid_from: string | null
  attestations: { onchain_id: number; contract_id: string; matches: boolean; revoked: boolean; detail: string
                  attestation_path: string | null; explorer_url: string | null
                  contract_explorer_url: string }[]
  checked_at: string
}
```

### Wallets
- `POST /wallets/challenge` `{ public_address, method? }` → `{ method, challenge_xdr, message, authorization_entries, network_passphrase, expires_at }`. `method` is `sep10` (a challenge transaction, the default for `G…`), `sep53` (a message to sign) or `sep45` (Soroban authorization entries for contract accounts, the default for `C…`). Single use; nothing is ever submitted to the network.
- `POST /wallets/verify` `{ public_address, signed_challenge_xdr? | signed_message? | signed_authorization_entries?, wallet_app? }` → `Wallet`. The answer must match the method the challenge was issued with.
- `GET /wallets` → `Wallet[]` (each with `wallet_app`, `proof_method`, `is_primary` and `kind: account|contract`)
- `POST /wallets/{wallet_id}/primary` → `Wallet`. Chooses the wallet payouts go to.
- `DELETE /wallets/{wallet_id}` → `204`
- `GET /wallets/options` → `{ sponsorship: { enabled, sponsor_address, functions, daily_tx_limit, used_today }, passkey: { enabled, unavailable_reason, wasm_hash, rpc_url, network_passphrase } }`. What this deployment offers; both are off without a sponsor key.
- `GET /wallets/passkey` → `PasskeyWallet[]` (`status: DEPLOYING|ACTIVE|FAILED`, `linked`, `deploy_tx_hash`, `explorer_url`)
- `POST /wallets/passkey` `{ key_id, public_key, deploy_xdr }` → `201 PasskeyWallet`. Relays a passkey-kit wallet deployment through the platform sponsor. `422` when the deployment is not exactly the expected contract for that passkey, `409` when the wallet belongs to another account, `503` when passkey wallets are off.
- `GET /wallets/passkey/candidates?key_id` → `{ schema: 2, complete, indexedThroughLedger, candidates: [{ contractId, birthWasmHash, creationTransactionHash, creationLedger }] }`. The caller's own wallet for that credential, in passkey-kit's lookup shape.
- `GET /admin/sponsorship` → `SponsorshipOverview` (staff: `transaction:view_all`). Sponsor balance, today's spend, thresholds and the recent sponsored transactions.

### Bounties
- `GET /bounties` query: `q, category, skills (comma), tags (comma), difficulty, status (comma), min_reward, max_reward, deadline_before, deadline_after, funded_only (bool), sort = newest|deadline|reward_high|reward_low|popular, page, page_size` → `Page<BountySummary>`. Only PUBLIC, non-draft bounties. Default status filter: OPEN, FUNDING_PENDING, FUNDED, IN_PROGRESS, UNDER_REVIEW.
  - `popular` = `applications_count * 3 + bookmarks_count * 2 + views_last_7d`, ties broken by newest.
- `GET /bounties/featured` → `BountySummary[]` (max 6)
- `GET /bounties/mine?role=requester|contributor&status&page&page_size` → `Page<BountySummary>`
- `GET /bounties/saved?page&page_size` → `Page<BountySummary>`
- `POST /bounties` → `201 BountyDetail` (status DRAFT). Body:
  ```ts
  { title; short_description; description; category; difficulty; tags: string[]; required_skills: string[]
    reward_amount: string; reward_asset?: "XLM"; application_deadline?: string | null; completion_deadline?: string | null
    positions_available: number; eligibility_criteria?; submission_requirements?; acceptance_criteria?
    repository_url?; links?: {label, url}[]; visibility?: Visibility }
  ```
- `GET /bounties/{bounty_id_or_slug}` → `BountyDetail` (drafts visible only to owner/moderators)
- `PATCH /bounties/{bounty_id}` → `BountyDetail`. Content fields editable while DRAFT or OPEN (unfunded). Reward/positions only editable while DRAFT.
- `POST /bounties/{bounty_id}/publish` → `BountyDetail` (DRAFT → OPEN)
- `POST /bounties/{bounty_id}/cancel` `{ reason }` → `BountyDetail`. Unfunded: → CANCELLED. Funded: → CANCEL_REQUESTED (refund via chain action REFUND).
- `POST /bounties/{bounty_id}/bookmark` → `204`; `DELETE /bounties/{bounty_id}/bookmark` → `204`
- `POST /bounties/{bounty_id}/report` `{ reason }` → `201 { id }`
- `GET /bounties/{bounty_id}/activity?page&page_size` → `Page<ActivityItem>`
- `POST /bounties/{bounty_id}/feature` `{ featured: boolean }` → `BountyDetail` (ADMIN/MODERATOR)

### Applications
- `POST /bounties/{bounty_id}/applications` `{ cover_message, relevant_experience?, work_samples?: string[] }` → `201 Application`
- `GET /bounties/{bounty_id}/applications?status&page&page_size` → `Page<Application>` (bounty owner or moderator)
- `GET /applications/me?status&page&page_size` → `Page<Application>`
- `POST /applications/{id}/withdraw` → `Application` (PENDING or ACCEPTED-before-submission)
- `POST /applications/{id}/accept` `{ note? }` → `Application` (bounty must be FUNDED or IN_PROGRESS and have an open position)
- `POST /applications/{id}/reject` `{ note? }` → `Application`

### Submissions
- `POST /bounties/{bounty_id}/submissions` `{ description, evidence_url?, evidence_links?: string[], pull_request_urls?: string[], milestone_id? }` → `201 Submission` (assigned contributor only). `pull_request_urls` holds up to 5 GitHub pull request URLs, verified after the submission is created (see [github.md](github.md)).
- `GET /bounties/{bounty_id}/submissions?page&page_size` → `Page<Submission>` (owner, moderator, or own submissions for contributor)
- `GET /submissions/me?status&page&page_size` → `Page<Submission>`
- `GET /submissions/{id}` → `Submission`
- `PATCH /submissions/{id}` `{ description?, evidence_url?, evidence_links?, pull_request_urls? }` → `Submission` (while REVISION_REQUESTED; becomes RESUBMITTED, version += 1)
- `POST /submissions/{id}/request-revision` `{ feedback }` → `Submission`
- `POST /submissions/{id}/approve` `{ feedback? }` → `Submission` (creates PaymentRecord with status CREATED). `409 merged_pr_required` while the bounty requires a merged pull request and none is verified; the message names the problem and, when the on-chain review clock is running, says that silence still pays the contributor. `details` carries `pull_requests`, `onchain_review_pending` and `claimable_at`.
- `POST /submissions/{id}/reject` `{ reason }` → `Submission`

### Funding, payouts, and chain actions
The frontend runs every on-chain action through the same three steps: **prepare → sign in wallet → submit**, then polls the transaction until `CONFIRMED` or `FAILED`.

- `POST /bounties/{bounty_id}/chain/prepare` `{ action: ChainAction, wallet_address: string, submission_id?, assignment_id?, dispute_id?, amount?, submission_ids?, feedback? }` → `PreparedTransaction` (`submission_ids`: `BATCH_PAYOUT`, 2 to 10 approved submissions; `feedback`: `REQUEST_CHANGES` / `REJECT_SUBMISSION`, applied once the answer is confirmed)
- `POST /bounties/{bounty_id}/funding/prepare` `{ wallet_address, amount? }` → `PreparedTransaction` (alias of action FUND)
- `POST /bounties/{bounty_id}/funding/submit` `{ transaction_id, signed_xdr }` → `BlockchainTransaction`
- `GET /bounties/{bounty_id}/funding` → `{ funding_status: FundingStatus; escrow: EscrowView | null; transactions: BlockchainTransaction[] }`
- `POST /bounties/{bounty_id}/payouts/prepare` `{ wallet_address, submission_id }` → `PreparedTransaction` (alias of action PAYOUT)
- `POST /bounties/{bounty_id}/payouts/submit` `{ transaction_id, signed_xdr }` → `BlockchainTransaction`
- `POST /transactions/{transaction_id}/submit` `{ signed_xdr }` → `BlockchainTransaction` (generic submit for any prepared action; `signed_xdr` is the wallet-signed envelope)
- `GET /bounties/{bounty_id}/transactions` → `BlockchainTransaction[]`
- `GET /transactions/me?page&page_size` → `Page<BlockchainTransaction>`
- `GET /transactions/{transaction_id_or_hash}` → `BlockchainTransaction`. Accepts internal UUID or hash. Triggers a verification refresh if still SUBMITTED.
- `GET /payments/me?direction=received|sent&page&page_size` → `Page<PaymentRecord>`

### Notifications
- `GET /notifications?unread_only&page&page_size` → `Page<Notification> & { unread_count: number }`
- `POST /notifications/{id}/read` → `204`
- `POST /notifications/read-all` → `204`
- `GET /notification-preferences` → `{ email_enabled: boolean; types: Record<NotificationType, { in_app: boolean; email: boolean }> }`
- `PATCH /notification-preferences` (same shape, partial) → same

### Analytics
- `GET /analytics/public` → `PublicStats`
  ```ts
  type PublicStats = {
    network: string; generated_at: string
    registered_users: number; published_bounties: number; open_bounties: number; funded_bounties: number
    completed_bounties: number; verified_payout_volume: string; successful_transactions: number
    unique_transacting_wallets: number; methodology: Record<string, string>
  }
  ```
- `GET /analytics/me` → `{ requester: RequesterAnalytics; contributor: ContributorAnalytics }`
- `GET /analytics/requester` → `RequesterAnalytics` = `{ bounties_by_status: Record<BountyStatus, number>; total_escrowed: string; total_paid: string; applications_received: number; avg_time_to_first_application_hours: number | null; spending_by_month: { month: string; amount: string }[] }`
- `GET /analytics/contributor` → `ContributorAnalytics` = `{ applications_by_status: Record<ApplicationStatus, number>; submissions_by_status: Record<SubmissionStatus, number>; total_earned: string; earnings_by_month: { month: string; amount: string }[]; completed_count: number }`
- `GET /analytics/platform` (ADMIN/MODERATOR) → detailed platform metrics incl. activation, conversion, repeat contributors, failed transactions, time series.

### Dashboard
- `GET /dashboard` → `{ active_bounties: number; pending_applications_to_review: number; submissions_awaiting_review: number; pending_payments: number; my_pending_applications: number; my_active_assignments: number; revision_requests: number; recent_completed: BountySummary[]; recent_activity: ActivityItem[]; recommendations: BountySummary[]; recommendation_reasons: Record<string, RecommendationReason> }`
  `recommendations` is the top of the skill-graph ranking; `recommendation_reasons` is keyed by bounty id.

### Discovery: saved searches and recommendations
See [discovery.md](discovery.md) for the matching and ranking rules.

```ts
type AlertFrequency = 'INSTANT' | 'DAILY' | 'WEEKLY' | 'OFF'

/** Every marketplace filter, plus a rolling deadline window instead of fixed dates. */
type SavedSearchFilters = {
  q?: string | null; category?: Category[] | null; difficulty?: Difficulty[] | null
  status?: BountyStatus[] | null; skills?: string[] | null; tags?: string[] | null
  min_reward?: string | null; max_reward?: string | null
  asset?: string[] | null            // reward asset identifiers ("native", "CODE:ISSUER")
  deadline_within_days?: number | null   // 1..365; deadline_before / deadline_after are rejected
  funded_only?: boolean; sort?: BountySort | null
}

type SavedSearch = {
  id: string; name: string; filters: SavedSearchFilters
  alert_frequency: AlertFrequency; notify_in_app: boolean; notify_email: boolean; is_paused: boolean
  new_count: number                  // matched since last_viewed_at and still listed by the search
  last_viewed_at: string; next_digest_at: string | null; created_at: string; updated_at: string
}

type RecommendationReason = {
  matched_skills: string[]                             // skills the user has
  related_skills: { skill: string; via: string }[]      // reached through the skill graph
}
type Recommendation = { bounty: BountySummary; score: number; reason: RecommendationReason }
```

- `GET /saved-searches` → `SavedSearch[]` (the caller's own, newest first)
- `POST /saved-searches` `{ name, filters?, alert_frequency?, notify_in_app?, notify_email? }` → `201 SavedSearch`.
  Up to 25 per user (`409` beyond that). Choosing email opts the account into `SAVED_SEARCH_MATCH` emails.
- `GET /saved-searches/{id}` → `SavedSearch`
- `PATCH /saved-searches/{id}` `{ name?, filters?, alert_frequency?, notify_in_app?, notify_email?, is_paused? }` → `SavedSearch`
- `DELETE /saved-searches/{id}` → `204` (its matches cascade)
- `POST /saved-searches/{id}/viewed` → `SavedSearch` with `new_count: 0`
- `POST /saved-searches/unsubscribe` `{ token }` → `{ saved_search_id, name, alert_frequency: 'OFF' }`.
  **Public and CSRF-exempt**: authorised by the signed token in an alert email, and it can only turn alerts off.
  `422` for a malformed or wrongly signed token, `404` when the search is gone.
- `GET /recommendations?<marketplace filters>&page&page_size` → `Page<Recommendation> & { seed_skills: string[]; has_profile_skills: boolean }`.
  Signed in only. Excludes the caller's own bounties and ones they applied to. `sort` is ignored (the ranking is
  the order); every other marketplace filter applies. Empty `items` with `has_profile_skills: false` means the
  user has no skills to rank from yet.
- `GET /skills/related?skills=a,b&limit` → `{ skills: string[]; related: { skill, weight, via: string[], marketplace_skills: string[] }[]; computed_at: string | null }`.
  Public. `marketplace_skills` are the raw names to filter the marketplace by (empty when only tags use the skill).
- `POST /admin/discovery/digests/run` `{ frequency: 'DAILY' | 'WEEKLY' }` → `{ frequency, users, searches, matches }`
  (ADMIN). Sends pending digests immediately, ignoring the schedule. **Answers `404` unless
  `DISCOVERY_DIGEST_TRIGGER_ENABLED` is set**, so it does not exist in normal deployments.

### Questions (bounty Q&A)
Public to read, signed in to write. Bodies are Markdown, stored raw and rendered by the SPA without raw HTML
(see [security.md](security.md#input-handling)). Replies are one level deep: replying to a reply joins the same
thread.

- `GET /bounties/{bounty_ref}/questions?sort=newest|helpful&page&page_size` → `QuestionPage` (public)
- `POST /bounties/{bounty_id}/questions` `{ body }` → `201 Thread` (10–5,000 characters; verified email; 20 posts
  per 10 minutes per user, 60 per hour per IP)
- `POST /qa/posts/{post_id}/replies` `{ body }` → `201 Thread` (2–5,000 characters)
- `PATCH /qa/posts/{post_id}` `{ body }` → `Thread` (author only; sets `edited_at`)
- `DELETE /qa/posts/{post_id}` → `204` (author only; soft delete — the thread keeps its shape)
- `PUT /qa/posts/{post_id}/vote` → `QAVote`; `DELETE /qa/posts/{post_id}/vote` → `QAVote` (one per user, never your own post)
- `POST /qa/posts/{post_id}/accept` / `DELETE …/accept` → `Thread` (requester only, replies only, one per question)
- `POST /qa/posts/{post_id}/pin` / `DELETE …/pin` → `Thread` (requester only, questions only, up to 3 per bounty)
- `POST /qa/posts/{post_id}/report` `{ reason }` → `201 { id }` (goes to the moderation queue as `target_type: "QA_POST"`)
- `POST /admin/qa/posts/{post_id}/moderate` `{ action: "HIDE" | "UNHIDE", reason }` → `ModeratedPost`
  (`bounty:moderate`). Hiding also marks the post's open reports as actioned.

```ts
type QAPost = {
  id: string
  question_id: string          // the thread; a question's own id
  parent_id: string | null
  author: UserSummary | null   // null once deleted
  body: string | null          // null when deleted, or hidden and you are not its author or a moderator
  is_requester: boolean        // written by the bounty's requester
  is_mine: boolean
  is_pinned: boolean
  is_accepted: boolean
  upvotes: number
  viewer_voted: boolean
  is_deleted: boolean
  is_hidden: boolean
  hidden_reason: string | null // author and moderators only
  edited_at: string | null
  created_at: string
}
type Thread = QAPost & { replies: QAPost[]; reply_count: number; answered: boolean }
type QuestionPage = Page<Thread> & {
  questions_count: number      // visible questions, also on BountySummary.questions_count
  can_ask: boolean
  closed_reason: string | null // why posting is closed (draft, hidden, completed, cancelled, expired)
  viewer_is_requester: boolean
  viewer_is_moderator: boolean
}
```

### GitHub
Account linking and pull request verification; the rules are in [github.md](github.md).

- `GET /github/config` → `{ oauth_enabled, webhook_enabled, authenticated_api }` (public)
- `GET /github/account` → `GitHubAccount | null`
- `POST /github/account/challenge` `{ login }` → `{ login, challenge, filename, expires_at }` (10 per 15 min)
- `POST /github/account/verify-gist` `{ gist_url }` → `GitHubAccount`. `422 gist_not_found`,
  `422 gist_not_verified` (wrong owner or missing text), `422 challenge_expired`, `409 github_account_taken`.
- `POST /github/oauth/start` → `{ authorize_url }`; `POST /github/oauth/callback` `{ code, state }` →
  `GitHubAccount`. Both answer `400 github_oauth_disabled` unless an OAuth app is configured.
- `DELETE /github/account` → `204`
- `GET /users/{username}/github` → `{ login, avatar_url, profile_url, verified_at } | null` (public)
- `GET /submissions/{id}/pull-requests` → `PullRequest[]` (contributor, requester, `submission:view_all`)
- `POST /submissions/{id}/pull-requests` `{ url }` → `201 PullRequest` (contributor, while the submission is open)
- `DELETE /submissions/{id}/pull-requests/{pull_request_id}` → `204`
- `POST /submissions/{id}/pull-requests/recheck` → `PullRequest[]` (20 per 5 min per user)
- `POST /github/webhook` → `202 { ok, rechecks }`. Server-to-server, CSRF-exempt, HMAC-verified with
  `X-Hub-Signature-256`; `404` while `GITHUB_WEBHOOK_SECRET` is empty, `401 invalid_signature` otherwise.

```ts
type GitHubAccount = {
  github_id: number
  login: string
  avatar_url: string | null
  profile_url: string
  method: "GIST" | "OAUTH"
  proof_url: string | null     // the gist that proved it
  verified_at: string
}
type PullRequest = {
  id: string
  url: string
  repository: string           // "owner/name"
  number: number
  verification: "PENDING" | "VERIFIED" | "NOT_FOUND" | "REPO_MISMATCH" | "AUTHOR_MISMATCH" | "AUTHOR_NOT_LINKED" | "UNAVAILABLE"
  detail: string | null        // why it did not verify, in plain words
  state: "OPEN" | "CLOSED" | "MERGED" | null
  title: string | null
  author_login: string | null
  merged_at: string | null
  head_sha: string | null
  draft: boolean
  checks: "SUCCESS" | "FAILURE" | "PENDING" | "NONE" | null
  checks_passed: number
  checks_failed: number
  checks_pending: number
  check_runs: { name: string | null; status: string | null; conclusion: string | null }[]
  statuses: { context: string | null; state: string | null }[]
  last_checked_at: string | null
  next_check_at: string | null
}
```

### Disputes
- `POST /bounties/{bounty_id}/disputes` `{ reason, evidence_url?, contributor_id? }` → `201 Dispute` (requester or assigned contributor). `contributor_id` is required when the requester raises it and several contributors are assigned.
- `GET /disputes/me` → `Dispute[]`
- `GET /disputes/{id}` → `Dispute` (parties and moderators)
- `POST /disputes/{id}/evidence` `{ description, url? }` → `Dispute`
- `POST /disputes/{id}/assign` → `Dispute` (moderator assigns self)
- `POST /disputes/{id}/resolve` `{ resolution: DisputeResolution; note; contributor_amount? }` → `Dispute` (MODERATOR/ADMIN). Records the off-chain decision. If funds are in the on-chain escrow, the arbiter wallet must then sign chain action `RESOLVE_DISPUTE` (1-of-1 arbiter set), or the escrow's arbiters sign `DISPUTE_VOTE` until the threshold is reached. `SPLIT` needs a frozen v2 escrow and `contributor_amount` between 0 and the contributor's open reward (exclusive); the rest returns to the requester.
- `GET /disputes/{id}/arbitration` → `Arbitration` (parties and staff): the escrow's arbiter set, read live from the contract (`resolution_votes`), falling back to the verified mirror when the RPC is unavailable.

### Escrow v2

- `GET /escrow/config` → `EscrowConfig` (public). `contract_version` is read from the configured contract's `version()`.
- `GET /bounties/{bounty_id}/milestones` → `Milestone[]` (anyone who can see the bounty)
- `PUT /bounties/{bounty_id}/milestones` `{ milestones: { title, description?, amount }[] }` → `Milestone[]` (owner, DRAFT only). 2 to 20 milestones on a single-position bounty, adding up to `reward_amount`; an empty list removes them. `POST /bounties` and `PATCH /bounties/{id}` also take `milestones` and `review_window_seconds`.
- `POST /bounties/{bounty_id}/submissions` takes `milestone_id` (required on a milestone bounty; one live submission per milestone).
- While a submission's clock runs on-chain, `POST /submissions/{id}/request-revision` and `/reject` answer `409 onchain_review_pending`: sign `REQUEST_CHANGES` / `REJECT_SUBMISSION` instead.
- Approving a milestone submission creates a payment for that milestone's amount, paid with `MILESTONE_PAYOUT` (or `BATCH_PAYOUT`). `PAYOUT` on a milestone bounty answers `409`.

```ts
type Milestone = {
  id: string; position: number; title: string; description: string | null; amount: string
  status: "OPEN" | "PAID" | "SETTLED"   // PAID / SETTLED only after the payout was verified on-chain
  paid_at: string | null; payout_transaction_id: string | null; explorer_url: string | null
}
type OnchainReview = {
  state: "PENDING" | "CHANGES_REQUESTED" | "REJECTED" | "PAID"
  submitted_at: string | null; claimable_at: string | null   // claim opens at claimable_at
  can_claim: boolean; can_answer: boolean                     // server view at response time; the contract decides
}
type EscrowConfig = {
  contract_id: string | null; contract_version: number
  default_review_window_seconds: number; min_review_window_seconds: number; max_review_window_seconds: number
  arbiter_addresses: string[]; arbiter_threshold: number; max_milestones: number; max_batch: number
}
type Arbitration = {
  dispute_id: string; contract_version: number; escrow_frozen: boolean; executed: boolean
  round: number; threshold: number; approvals: number
  arbiters: { address: string; staff: UserSummary | null; approved: boolean; contributor_amount: string | null }[]
  resolution: DisputeResolution | null; contributor_amount: string | null; requester_amount: string | null
  position_value: string | null
  my_arbiter_wallets: string[]; my_vote_recorded: boolean; can_vote: boolean; vote_blocked_reason: string | null
}
```

### Reward assets and trustlines
- `GET /assets` → `RewardAsset[]` (public): the enabled reward assets on this network.
  `RewardAsset = { id, asset: Asset, name, is_default, requires_trustline, faucet_url }`
- `GET /assets/wallets` → `WalletAssets[]`: each verified wallet of the caller with its XLM balance and, per
  enabled asset, whether it can receive it.
  `WalletAssets = { wallet_id, address, network, account_exists, native_balance, native_spendable, trustlines: TrustlineStatus[] }`,
  `TrustlineStatus = { asset: Asset, address, state: TrustlineState, balance }`
  `TrustlineState = "NOT_REQUIRED" | "ACTIVE" | "MISSING" | "UNAUTHORIZED" | "ACCOUNT_MISSING" | "NO_WALLET" | "UNKNOWN"`
- `POST /assets/{asset_id}/trustline/prepare` `{ wallet_address }` → `PreparedAssetOperation`: an unsigned
  `changeTrust` from that verified wallet.
- `POST /assets/operations/{id}/submit` `{ signed_xdr }` → `AssetOperation`
- `GET /assets/operations/{id}` → `AssetOperation` (polled like a transaction; `CONFIRMED` only once the
  trustline, or the deployed contract, reads back from the network)
  `AssetOperation = { id, kind: "TRUSTLINE" | "DEPLOY_CONTRACT", status, asset, network, source_address, transaction_hash, ledger_sequence, submitted_at, confirmed_at, failure_reason, explorer_url, created_at }`
- `GET /bounties/{id}/trustlines` → `{ asset, requires_trustline, applicants: { contributor_id, address, state }[] }`
  (requester or `application:view_all`)
- `GET /bounties/{id}/funding/readiness?wallet_address=G…` →
  `{ asset, address, required, available, trustline, ready, message, faucet_url }` (requester only)

A bounty picks its asset at creation: `POST /bounties` accepts `reward_asset` as `"native"`, `"XLM"`, a full
`"CODE:ISSUER"`, or a bare code when exactly one enabled asset uses it (default XLM). It can still be changed
while the bounty is a `DRAFT`. The marketplace filters on it: `GET /bounties?asset=USDC:G…` (comma-separated).

### Privacy and legal
- `GET /privacy/exports` → `DataExport[]` (the caller's own, newest first). A `READY` export carries
  `download_url`, a signed path valid for a few minutes; fetch the list again for a fresh one.
- `POST /privacy/exports` → `202 DataExport`: queues an archive the worker builds. 409 while one is being built,
  and at most 3 a day.
- `GET /privacy/exports/{id}/download?expires&signature` → the JSON archive as an attachment. Needs the owner's
  session **and** an unexpired signature; 403 when the link expired, 404 when the archive is gone.
- `GET /privacy/deletion` → `{ request, blockers, grace_days }`. `blockers` is empty when the account can be
  deleted; each entry is `{ kind, message, count, links }`.
- `POST /privacy/deletion` `{ password, reason? }` → `201` the same shape. 422 `invalid_password`, or 409
  `deletion_blocked` with the blockers in `details`.
- `POST /privacy/deletion/cancel` → the same shape (404 when nothing is scheduled).
- `GET /legal/versions` → `LegalVersion[]` **(public)**: the terms and privacy notice versions in effect.
- `GET /legal/status` → `{ documents, needs_acceptance, upcoming_pending }`. `needs_acceptance` gates the
  workspace; `upcoming_pending` is advance notice of a scheduled version.
- `POST /legal/accept` `{ version_ids }` → the same shape. Only versions in effect or scheduled are accepted.

### Admin (MODERATOR/ADMIN unless noted)
- `GET /admin/overview` → counts + health snapshot
- `GET /admin/users?q&role&page&page_size` → `Page<AdminUser>`; `AdminUser = UserSummary & { email, role, is_active, email_verified, created_at }`
- `PATCH /admin/users/{id}` `{ is_active?, role? }` → `AdminUser` (role changes ADMIN only)
- `GET /admin/bounties?q&status&page&page_size` → `Page<BountySummary>`
- `POST /admin/bounties/{id}/moderate` `{ action: "HIDE" | "UNHIDE" | "CANCEL", reason }` → `BountyDetail`
- `GET /admin/reports?status&target_type&page&page_size` → `Page<{ id, reporter: UserSummary, target_type, target_id, reason, status, created_at, resolution_note, target_summary }>`. For a `QA_POST` report `target_summary` carries `{ label, excerpt, link, author, is_hidden, is_deleted, bounty_id }` so the queue shows what was reported without a second request.
- `POST /admin/reports/{id}/resolve` `{ status: "ACTIONED" | "DISMISSED", note }` → report
- `GET /admin/disputes?status&page&page_size` → `Page<Dispute>`
- `GET /admin/transactions?status&type&page&page_size` → `Page<BlockchainTransaction>`
- `GET /admin/audit-logs?entity_type&action&page&page_size` → `Page<{ id, actor: UserSummary | null, action, entity_type, entity_id, metadata, created_at }>`
- Additional filters: `GET /admin/users?is_active`, `GET /admin/bounties?hidden`, `GET /admin/reports?target_type`, `GET /admin/audit-logs?entity_id&actor_id`.
- `GET /admin/assets` → `AdminRewardAsset[]` (`asset:manage`, ADMIN): the whole registry, enabled or not, with
  `is_enabled`, `contract_status`, `symbol`, `decimals`, `issuer_flags`, `bounty_count` and `verified_at`.
- `POST /admin/assets` `{ code?, issuer?, contract_id?, name?, enable? }` → `AdminRewardAsset`: a classic asset by
  code and issuer, or by its Stellar Asset Contract id. The backend derives the SAC address, checks the contract
  answers the token interface with 7 decimals and reads the issuer's flags; an asset whose SAC is not deployed
  is created disabled.
- `PATCH /admin/assets/{id}` `{ is_enabled?, name?, sort_order? }` → `AdminRewardAsset` (the last enabled asset
  cannot be disabled; an asset whose contract is not deployed cannot be enabled)
- `POST /admin/assets/{id}/verify` → `AdminRewardAsset`: re-reads the contract and issuer from the network.
- `POST /admin/assets/{id}/deploy/prepare` `{ wallet_address }` → `PreparedAssetOperation`: deploys the asset's
  Stellar Asset Contract, signed by the admin's verified wallet and submitted through `/assets/operations/{id}/submit`.
- `POST /admin/bounties/{id}/reconcile` → `BountyDetail` (`transaction:view_all`): re-reads the escrow from the contract and refreshes the stored escrow view.
- `GET /admin/compliance/deletions?status&page&page_size` → `Page<AdminDeletionRequest>` (`audit:read`): pending
  and past deletion requests, each with the live `blockers` and, once carried out, the `pseudonym`.
- `GET /admin/compliance/screening/status` → `{ enabled, provider, manual_entries, list_entries, list }`
  (`audit:read`): whether screening is on, and when the configured sanctions list last loaded or failed.
- `GET /admin/compliance/screening/entries?q&source&include_removed&page&page_size` → `Page<ScreeningEntry>`
  (`audit:read`).
- `POST /admin/compliance/screening/entries` `{ address, reason }` → `201 ScreeningEntry` (**ADMIN**). Blocks a
  `G…` or `C…` address at wallet verification, funding and every payout.
- `POST /admin/compliance/screening/entries/{id}/remove` `{ note }` → `ScreeningEntry` (**ADMIN**). Only manual
  entries; list entries change only when the list does.
- `GET /admin/compliance/screening/decisions?result&q&page&page_size` → `Page<ScreeningDecision>`
  (`audit:read`): blocked (default) or cleared decisions, with the matching entry and its reason.
- `GET /admin/compliance/legal/versions` → `AdminLegalVersion[]` (`audit:read`), with `accepted_count`.
- `POST /admin/compliance/legal/versions` `{ document, version, summary, effective_at? }` → `201` (**ADMIN**).
  Without `effective_at` the version is in effect at once and the workspace asks users to accept it.
- `POST /admin/compliance/legal/versions/{id}/withdraw` → `AdminLegalVersion` (**ADMIN**): only a version that
  has not taken effect yet.
- `GET /admin/ops/status` → `{ jobs, workers, kafka_lag, reconciliation }` (`system:health`): worker job health,
  heartbeat ages, consumer lag and the last chain-versus-database audit.
- `GET /metrics` (**not** under `/api/v1`, not in the OpenAPI document): Prometheus text. Needs
  `Authorization: Bearer $METRICS_TOKEN`, or a direct loopback request when no token is set; anything else 404s.

## Staff response shapes

```ts
// GET /admin/overview  (permission system:health)
type AdminOverview = {
  generated_at: string; network: string
  counts: { users_total: number; users_active_30d: number; users_suspended: number; bounties_total: number
            bounties_open: number; bounties_hidden: number; open_reports: number; open_disputes: number
            pending_transactions: number; failed_transactions_24h: number; unpublished_outbox_events: number }
  health: { database: Check; redis: Check; kafka: Check; blockchain_rpc: Check; worker: Check }  // "ok" | "error" | "disabled"
  worker_heartbeat_at: string | null
}

// GET /analytics/platform  (permission analytics:platform)
type PlatformAnalytics = {
  network: string; generated_at: string
  users: { registered_users: number; verified_users: number; connected_wallets: number; active_users_30d: number
           email_verification_rate: number | null; wallet_connection_rate: number | null }
  bounties: { published_bounties: number; open_bounties: number; funded_bounties: number; completed_bounties: number }
  transactions: { unique_transacting_wallets: number; successful_transactions: number; failed_transactions: number
                  verified_payout_volume: string }
  engagement: { repeat_contributors: number; applications_decided: number; application_acceptance_rate: number | null
                submissions_reviewed: number; submission_approval_rate: number | null }
  time_series: { day: string; registrations: number; bounties_published: number; bounties_funded: number
                 bounties_completed: number; applications: number; submissions: number
                 payouts_confirmed_count: number; payout_volume: string }[]   // last 30 days, from daily_metrics
  methodology: Record<string, string>
}
```
