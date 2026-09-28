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
- Assets:

```ts
type Asset = { code: "XLM"; issuer: null; type: "native"; contract_id: string | null }
```

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
type ChainAction = "FUND" | "ASSIGN" | "PAYOUT" | "REQUEST_CANCEL" | "CONSENT_CANCEL" | "REFUND" | "RAISE_DISPUTE" | "RESOLVE_DISPUTE"
type DisputeStatus = "OPEN" | "UNDER_REVIEW" | "RESOLVED" | "DISMISSED"
type DisputeResolution = "RELEASE_TO_CONTRIBUTOR" | "REFUND_TO_REQUESTER" | "DISMISSED"
type ReportStatus = "OPEN" | "REVIEWING" | "ACTIONED" | "DISMISSED"
type NotificationType = "BOUNTY_PUBLISHED" | "BOUNTY_FUNDED" | "APPLICATION_RECEIVED" | "APPLICATION_ACCEPTED"
  | "APPLICATION_REJECTED" | "SUBMISSION_RECEIVED" | "REVISION_REQUESTED" | "SUBMISSION_APPROVED"
  | "SUBMISSION_REJECTED" | "PAYMENT_CONFIRMED" | "BOUNTY_CANCELLED" | "BOUNTY_EXPIRED" | "DISPUTE_UPDATE" | "SYSTEM"
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

### Wallets
- `POST /wallets/challenge` `{ public_address }` → `{ challenge_xdr, network_passphrase, expires_at }`. SEP-10-style challenge transaction; the wallet signs it (it is never submitted to the network).
- `POST /wallets/verify` `{ public_address, signed_challenge_xdr }` → `Wallet`
- `GET /wallets` → `Wallet[]`
- `DELETE /wallets/{wallet_id}` → `204`

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
- `POST /bounties/{bounty_id}/submissions` `{ description, evidence_url?, evidence_links?: string[] }` → `201 Submission` (assigned contributor only)
- `GET /bounties/{bounty_id}/submissions?page&page_size` → `Page<Submission>` (owner, moderator, or own submissions for contributor)
- `GET /submissions/me?status&page&page_size` → `Page<Submission>`
- `GET /submissions/{id}` → `Submission`
- `PATCH /submissions/{id}` `{ description?, evidence_url?, evidence_links? }` → `Submission` (while REVISION_REQUESTED; becomes RESUBMITTED, version += 1)
- `POST /submissions/{id}/request-revision` `{ feedback }` → `Submission`
- `POST /submissions/{id}/approve` `{ feedback? }` → `Submission` (creates PaymentRecord with status CREATED)
- `POST /submissions/{id}/reject` `{ reason }` → `Submission`

### Funding, payouts, and chain actions
The frontend runs every on-chain action through the same three steps: **prepare → sign in wallet → submit**, then polls the transaction until `CONFIRMED` or `FAILED`.

- `POST /bounties/{bounty_id}/chain/prepare` `{ action: ChainAction, wallet_address: string, submission_id?, assignment_id?, dispute_id?, amount? }` → `PreparedTransaction`
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
- `GET /dashboard` → `{ active_bounties: number; pending_applications_to_review: number; submissions_awaiting_review: number; pending_payments: number; my_pending_applications: number; my_active_assignments: number; revision_requests: number; recent_completed: BountySummary[]; recent_activity: ActivityItem[]; recommendations: BountySummary[] }`

### Disputes
- `POST /bounties/{bounty_id}/disputes` `{ reason, evidence_url?, contributor_id? }` → `201 Dispute` (requester or assigned contributor). `contributor_id` is required when the requester raises it and several contributors are assigned.
- `GET /disputes/me` → `Dispute[]`
- `GET /disputes/{id}` → `Dispute` (parties and moderators)
- `POST /disputes/{id}/evidence` `{ description, url? }` → `Dispute`
- `POST /disputes/{id}/assign` → `Dispute` (moderator assigns self)
- `POST /disputes/{id}/resolve` `{ resolution: DisputeResolution; note }` → `Dispute` (MODERATOR/ADMIN). Records the off-chain decision. If funds are in the on-chain escrow, the arbiter wallet must then sign chain action `RESOLVE_DISPUTE`.

### Admin (MODERATOR/ADMIN unless noted)
- `GET /admin/overview` → counts + health snapshot
- `GET /admin/users?q&role&page&page_size` → `Page<AdminUser>`; `AdminUser = UserSummary & { email, role, is_active, email_verified, created_at }`
- `PATCH /admin/users/{id}` `{ is_active?, role? }` → `AdminUser` (role changes ADMIN only)
- `GET /admin/bounties?q&status&page&page_size` → `Page<BountySummary>`
- `POST /admin/bounties/{id}/moderate` `{ action: "HIDE" | "UNHIDE" | "CANCEL", reason }` → `BountyDetail`
- `GET /admin/reports?status&page&page_size` → `Page<{ id, reporter: UserSummary, target_type, target_id, reason, status, created_at, resolution_note }>`
- `POST /admin/reports/{id}/resolve` `{ status: "ACTIONED" | "DISMISSED", note }` → report
- `GET /admin/disputes?status&page&page_size` → `Page<Dispute>`
- `GET /admin/transactions?status&type&page&page_size` → `Page<BlockchainTransaction>`
- `GET /admin/audit-logs?entity_type&action&page&page_size` → `Page<{ id, actor: UserSummary | null, action, entity_type, entity_id, metadata, created_at }>`
- Additional filters: `GET /admin/users?is_active`, `GET /admin/bounties?hidden`, `GET /admin/reports?target_type`, `GET /admin/audit-logs?entity_id&actor_id`.
- `POST /admin/bounties/{id}/reconcile` → `BountyDetail` (`transaction:view_all`): re-reads the escrow from the contract and refreshes the stored escrow view.

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
