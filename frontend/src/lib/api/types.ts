/**
 * TypeScript mirror of docs/api.md (BountyFlow REST API contract).
 * Keep this file in lock-step with the contract: every enum and shape below
 * corresponds 1:1 to a definition in the document.
 */

// ---------------------------------------------------------------------------
// Conventions
// ---------------------------------------------------------------------------

/** Decimal string with up to 7 fractional digits, e.g. "250.5000000". Never a float. */
export type DecimalString = string
/** ISO 8601 UTC timestamp, e.g. "2026-09-25T12:00:00Z". */
export type ISODateTime = string

export type Page<T> = { items: T[]; total: number; page: number; page_size: number; pages: number }

export type PageParams = { page?: number; page_size?: number }

export type ApiErrorCode =
  | 'validation_error'
  | 'not_authenticated'
  | 'token_expired'
  | 'forbidden'
  | 'csrf_failed'
  | 'not_found'
  | 'conflict'
  | 'invalid_state_transition'
  | 'rate_limited'
  | 'blockchain_error'
  | 'internal_error'
  /** 403 — publishing requires a verified email (backend addition). */
  | 'email_not_verified'
  /** 422 — accepting an applicant who has no verified wallet (backend addition). */
  | 'contributor_wallet_missing'
  /** 409 — the on-chain escrow at this bounty's id was not created by BountyFlow with the expected terms (backend addition). */
  | 'escrow_unverified'
  /** 403 — the wallet used for a chain action is not linked + verified on the account (backend addition). */
  | 'wallet_not_verified'
  /** 422 — the escrow contract rejected the action while it was being prepared; `details.contract_error` names the error. */
  | 'contract_rejected'
  /** 422 — sign with the wallet recorded on the escrow / on-chain assignment. */
  | 'wrong_wallet'
  /** 422 — the wallet account does not exist on the network yet. */
  | 'account_not_found'
  /** 422 — the signed envelope does not match the prepared transaction. */
  | 'signature_invalid'
  /** 503 — a required component (escrow config, Redis) is unavailable. */
  | 'service_unavailable'
  | 'method_not_allowed'
  | 'payload_too_large'

export type ValidationErrorDetail = { field: string; message: string }

export type ErrorEnvelope = {
  error: {
    code: ApiErrorCode | (string & {})
    message: string
    details?: unknown[] | null
    request_id?: string | null
  }
}

export type Asset = { code: 'XLM'; issuer: null; type: 'native'; contract_id: string | null }

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

export const ROLES = ['USER', 'MODERATOR', 'ADMIN'] as const
export type Role = (typeof ROLES)[number]

/**
 * RBAC permissions carried on `Me.permissions` (backend addition). UI is gated
 * by permission, never by role name. Unknown future permissions are allowed.
 */
export const PERMISSIONS = [
  'bounty:create',
  'bounty:moderate',
  'bounty:feature',
  'bounty:view_all',
  'dispute:view_all',
  'dispute:resolve',
  'report:review',
  'user:view_all',
  'user:manage',
  'user:assign_role',
  'audit:read',
  'transaction:view_all',
  'analytics:platform',
  'system:health',
] as const
export type KnownPermission = (typeof PERMISSIONS)[number]
export type Permission = KnownPermission | (string & {})

export const BOUNTY_STATUSES = [
  'DRAFT',
  'OPEN',
  'FUNDING_PENDING',
  'FUNDED',
  'IN_PROGRESS',
  'UNDER_REVIEW',
  'COMPLETED',
  'CANCEL_REQUESTED',
  'CANCELLED',
  'DISPUTED',
  'EXPIRED',
] as const
export type BountyStatus = (typeof BOUNTY_STATUSES)[number]

export const FUNDING_STATUSES = [
  'UNFUNDED',
  'PENDING',
  'PARTIALLY_FUNDED',
  'FUNDED',
  'REFUND_PENDING',
  'REFUNDED',
  'SETTLED',
] as const
export type FundingStatus = (typeof FUNDING_STATUSES)[number]

export const CATEGORIES = [
  'DEVELOPMENT',
  'BUG_BOUNTY',
  'DESIGN',
  'SECURITY',
  'DOCUMENTATION',
  'RESEARCH',
  'COMMUNITY',
  'OTHER',
] as const
export type Category = (typeof CATEGORIES)[number]

export const DIFFICULTIES = ['BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'EXPERT'] as const
export type Difficulty = (typeof DIFFICULTIES)[number]

export const VISIBILITIES = ['PUBLIC', 'UNLISTED'] as const
export type Visibility = (typeof VISIBILITIES)[number]

export const APPLICATION_STATUSES = ['PENDING', 'ACCEPTED', 'REJECTED', 'WITHDRAWN'] as const
export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number]

export const SUBMISSION_STATUSES = [
  'SUBMITTED',
  'REVISION_REQUESTED',
  'RESUBMITTED',
  'APPROVED',
  'REJECTED',
] as const
export type SubmissionStatus = (typeof SUBMISSION_STATUSES)[number]

export const PAYMENT_STATUSES = [
  'NOT_REQUIRED',
  'CREATED',
  'SIGNATURE_REQUIRED',
  'SUBMITTED',
  'CONFIRMED',
  'FAILED',
  'REFUND_PENDING',
  'REFUNDED',
] as const
export type PaymentStatus = (typeof PAYMENT_STATUSES)[number]

export const TX_STATUSES = [
  'CREATED',
  'SIGNATURE_REQUIRED',
  'SUBMITTED',
  'CONFIRMED',
  'FAILED',
  'EXPIRED',
] as const
export type TxStatus = (typeof TX_STATUSES)[number]

export const TX_TYPES = [
  'ESCROW_CREATE',
  'ESCROW_FUND',
  'ASSIGN',
  'PAYOUT',
  'CANCEL_REQUEST',
  'CANCEL_CONSENT',
  'REFUND',
  'DISPUTE_RAISE',
  'DISPUTE_RESOLVE',
  'WALLET_CHALLENGE',
] as const
export type TxType = (typeof TX_TYPES)[number]

export const CHAIN_ACTIONS = [
  'FUND',
  'ASSIGN',
  'PAYOUT',
  'REQUEST_CANCEL',
  'CONSENT_CANCEL',
  'REFUND',
  'RAISE_DISPUTE',
  'RESOLVE_DISPUTE',
] as const
export type ChainAction = (typeof CHAIN_ACTIONS)[number]

export const DISPUTE_STATUSES = ['OPEN', 'UNDER_REVIEW', 'RESOLVED', 'DISMISSED'] as const
export type DisputeStatus = (typeof DISPUTE_STATUSES)[number]

export const DISPUTE_RESOLUTIONS = ['RELEASE_TO_CONTRIBUTOR', 'REFUND_TO_REQUESTER', 'DISMISSED'] as const
export type DisputeResolution = (typeof DISPUTE_RESOLUTIONS)[number]

export const REPORT_STATUSES = ['OPEN', 'REVIEWING', 'ACTIONED', 'DISMISSED'] as const
export type ReportStatus = (typeof REPORT_STATUSES)[number]

export const NOTIFICATION_TYPES = [
  'BOUNTY_PUBLISHED',
  'BOUNTY_FUNDED',
  'APPLICATION_RECEIVED',
  'APPLICATION_ACCEPTED',
  'APPLICATION_REJECTED',
  'SUBMISSION_RECEIVED',
  'REVISION_REQUESTED',
  'SUBMISSION_APPROVED',
  'SUBMISSION_REJECTED',
  'PAYMENT_CONFIRMED',
  'BOUNTY_CANCELLED',
  'BOUNTY_EXPIRED',
  'DISPUTE_UPDATE',
  'SYSTEM',
] as const
export type NotificationType = (typeof NOTIFICATION_TYPES)[number]

/** `relevance` is the API default when `q` is set (backend addition). */
export const BOUNTY_SORTS = [
  'relevance',
  'newest',
  'deadline',
  'reward_high',
  'reward_low',
  'popular',
] as const
export type BountySort = (typeof BOUNTY_SORTS)[number]

export type EscrowState =
  'NOT_CREATED' | 'AWAITING_FUNDING' | 'FUNDED' | 'CANCEL_REQUESTED' | 'DISPUTED' | 'COMPLETED' | 'CANCELLED'

export type BlockchainMode = 'testnet' | 'mainnet'

// ---------------------------------------------------------------------------
// Shared shapes
// ---------------------------------------------------------------------------

export type UserSummary = { id: string; username: string; display_name: string; avatar_url: string | null }

export type OnboardingState = {
  email_verified: boolean
  profile_completed: boolean
  role_selected: boolean
  wallet_connected: boolean
  first_action_taken: boolean
  completed: boolean
}

export type Me = {
  id: string
  email: string
  email_verified: boolean
  username: string
  display_name: string
  avatar_url: string | null
  bio: string | null
  role: Role
  skills: string[]
  interests: string[]
  github_url: string | null
  portfolio_url: string | null
  wants_to_request: boolean
  wants_to_contribute: boolean
  onboarding: OnboardingState
  /** RBAC permissions (backend addition). */
  permissions: Permission[]
  created_at: ISODateTime
}

export type Wallet = {
  id: string
  public_address: string
  network: string
  verification_status: 'VERIFIED'
  verified_at: ISODateTime
  created_at: ISODateTime
}

export type UserStats = {
  bounties_created: number
  bounties_completed_as_requester: number
  contributions_completed: number
  applications_submitted: number
  /** 0..1, accepted / decided applications */
  acceptance_rate: number | null
  /** 0..1, approved / reviewed submissions */
  approval_rate: number | null
  /** XLM, only CONFIRMED on-chain payouts */
  total_rewards_received: DecimalString
  total_rewards_paid: DecimalString
}

export type PublicWallet = {
  public_address: string
  network: string
  verified_at: ISODateTime
}

export type PublicProfile = {
  id: string
  username: string
  display_name: string
  avatar_url: string | null
  bio: string | null
  skills: string[]
  interests: string[]
  github_url: string | null
  portfolio_url: string | null
  joined_at: ISODateTime
  wallets: PublicWallet[]
  stats: UserStats
}

export type EscrowView = {
  contract_id: string | null
  network: string
  asset: Asset
  onchain_bounty_id: string
  required_amount: DecimalString
  funded_amount: DecimalString
  paid_out_amount: DecimalString
  refunded_amount: DecimalString
  state: EscrowState
  last_reconciled_at: ISODateTime | null
  /** Explorer link for the escrow contract/state (backend addition). */
  explorer_url: string | null
}

export type BountySummary = {
  id: string
  slug: string
  title: string
  short_description: string
  category: Category
  difficulty: Difficulty
  tags: string[]
  required_skills: string[]
  /** Reward PER POSITION. */
  reward_amount: DecimalString
  reward_asset: Asset
  total_reward: DecimalString
  network: string
  status: BountyStatus
  funding_status: FundingStatus
  application_deadline: ISODateTime | null
  completion_deadline: ISODateTime | null
  positions_available: number
  positions_filled: number
  applications_count: number
  requester: UserSummary
  is_featured: boolean
  is_bookmarked: boolean
  /** Hidden by moderation; only ever true for owners and staff (backend addition). */
  is_hidden?: boolean
  created_at: ISODateTime
  published_at: ISODateTime | null
}

export type BountyLink = { label: string; url: string }

export type BountyViewer = {
  is_owner: boolean
  /** Viewer holds moderation permissions (backend addition). */
  is_moderator: boolean
  is_assigned: boolean
  can_apply: boolean
  can_submit: boolean
  application: { id: string; status: ApplicationStatus } | null
  assignment_id: string | null
}

export type BountyDetail = BountySummary & {
  /** Markdown (render safely, no raw HTML) */
  description: string
  eligibility_criteria: string | null
  submission_requirements: string | null
  acceptance_criteria: string | null
  repository_url: string | null
  links: BountyLink[]
  visibility: Visibility
  /** Hidden by moderation (backend addition). */
  is_hidden: boolean
  cancel_reason: string | null
  escrow: EscrowView | null
  /** null for anonymous viewers */
  viewer: BountyViewer | null
}

export type BountyRef = { id: string; slug: string; title: string; status: BountyStatus }
export type BountyRefLite = { id: string; slug: string; title: string }

export type Application = {
  id: string
  bounty_id: string
  bounty: BountyRef
  contributor: UserSummary & { skills: string[] }
  cover_message: string
  relevant_experience: string | null
  work_samples: string[]
  status: ApplicationStatus
  /** Set once accepted; needed for ASSIGN / CONSENT_CANCEL chain actions (backend addition). */
  assignment_id: string | null
  /** The contributor is locked in the escrow contract via ASSIGN (backend addition). */
  onchain_assigned?: boolean
  /** only visible to the bounty owner */
  review_note: string | null
  reviewed_at: ISODateTime | null
  created_at: ISODateTime
  updated_at: ISODateTime
}

export type BlockchainTransaction = {
  id: string
  bounty_id: string | null
  bounty_title: string | null
  /** Backend addition. */
  bounty_slug?: string | null
  user: UserSummary | null
  transaction_hash: string | null
  transaction_type: TxType
  network: string
  amount: DecimalString | null
  asset: Asset | null
  status: TxStatus
  source_address: string | null
  destination_address: string | null
  /** Contract invoked, when known (backend addition). */
  contract_id?: string | null
  function_name?: string | null
  ledger_sequence: number | null
  submitted_at: ISODateTime | null
  confirmed_at: ISODateTime | null
  failure_reason: string | null
  explorer_url: string | null
  created_at: ISODateTime
}

export type PaymentRecord = {
  id: string
  bounty_id: string
  /** Backend addition: lets payment lists link to the bounty without the transaction. */
  bounty_title?: string | null
  bounty_slug?: string | null
  contributor: UserSummary
  submission_id: string
  amount: DecimalString
  asset: Asset
  payment_status: PaymentStatus
  transaction: BlockchainTransaction | null
  created_at: ISODateTime
  settled_at: ISODateTime | null
}

export type Submission = {
  id: string
  bounty_id: string
  bounty: BountyRef
  contributor: UserSummary
  assignment_id: string
  version: number
  description: string
  evidence_url: string | null
  evidence_links: string[]
  status: SubmissionStatus
  review_feedback: string | null
  reviewer: UserSummary | null
  reviewed_at: ISODateTime | null
  payment: PaymentRecord | null
  /** Earlier versions, oldest first (backend addition). */
  revisions?: SubmissionRevision[]
  created_at: ISODateTime
  updated_at: ISODateTime
}

export type SubmissionRevision = {
  version: number
  description: string
  evidence_url: string | null
  evidence_links: string[]
  created_at: ISODateTime
}

export type PreparedTransactionSummary = {
  action: ChainAction
  description: string
  amount: DecimalString | null
  asset: Asset | null
  fee_estimate_stroops: string | null
  contract_id: string | null
  function_name: string
}

export type PreparedTransaction = {
  /** status SIGNATURE_REQUIRED */
  transaction: BlockchainTransaction
  /** The exact transaction the wallet must sign. */
  unsigned_xdr: string
  network_passphrase: string
  network: string
  summary: PreparedTransactionSummary
  expires_at: ISODateTime
}

export type ActivityItem = {
  id: string
  action: string
  actor: UserSummary | null
  entity_type: string
  entity_id: string
  bounty: BountyRefLite | null
  metadata: Record<string, unknown>
  created_at: ISODateTime
  link: string | null
}

export type Notification = {
  id: string
  notification_type: NotificationType
  title: string
  message: string
  payload: Record<string, unknown>
  link: string | null
  read_at: ISODateTime | null
  created_at: ISODateTime
}

export type DisputeEvidence = {
  id: string
  submitted_by: UserSummary
  description: string
  url: string | null
  created_at: ISODateTime
}

export type Dispute = {
  id: string
  bounty: BountyRefLite
  raised_by: UserSummary
  /** The assigned contributor the dispute concerns (backend addition). */
  contributor?: UserSummary | null
  reason: string
  status: DisputeStatus
  assigned_moderator: UserSummary | null
  resolution: DisputeResolution | null
  resolution_note: string | null
  evidence: DisputeEvidence[]
  /** The escrow is frozen on-chain (RAISE_DISPUTE confirmed) (backend addition). */
  escrow_frozen_onchain?: boolean
  /**
   * A release/refund decision was recorded while the escrow is frozen, so the
   * escrow's arbiter wallet must still sign RESOLVE_DISPUTE (backend addition).
   */
  requires_onchain_execution?: boolean
  created_at: ISODateTime
  resolved_at: ISODateTime | null
}

// ---------------------------------------------------------------------------
// Health & config
// ---------------------------------------------------------------------------

export type HealthResponse = { status: 'ok'; service: string; version: string }
export type HealthLiveResponse = { status: 'ok' }
export type HealthCheckState = 'ok' | 'error' | 'disabled'
export type HealthReadyResponse = {
  status: 'ok' | 'degraded'
  checks: {
    database: HealthCheckState
    redis: HealthCheckState
    kafka: HealthCheckState
    blockchain_rpc: HealthCheckState
  }
}

export type PublicConfig = {
  app_name: string
  network: string
  network_passphrase: string
  horizon_url: string
  soroban_rpc_url: string
  explorer_base_url: string
  contract_id: string | null
  /** Explorer link for the escrow contract (backend addition). */
  contract_explorer_url?: string | null
  native_asset_contract_id: string | null
  arbiter_address: string | null
  blockchain_mode: BlockchainMode
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export type RegisterRequest = { email: string; password: string; username: string; display_name: string }
export type LoginRequest = { email: string; password: string }
export type VerifyEmailRequest = { token: string }
export type VerifyEmailResponse = Me | { verified: true }
export type ForgotPasswordRequest = { email: string }
export type ForgotPasswordResponse = { message: string }
export type ResetPasswordRequest = { token: string; password: string }
export type Session = {
  id: string
  created_at: ISODateTime
  last_used_at: ISODateTime | null
  user_agent: string | null
  is_current: boolean
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export type UpdateMeRequest = Partial<{
  display_name: string
  username: string
  avatar_url: string | null
  bio: string | null
  skills: string[]
  interests: string[]
  github_url: string | null
  portfolio_url: string | null
  wants_to_request: boolean
  wants_to_contribute: boolean
}>

export type Contribution = {
  bounty: BountySummary
  completed_at: ISODateTime
  amount: DecimalString | null
  transaction_hash: string | null
}

// ---------------------------------------------------------------------------
// Wallets
// ---------------------------------------------------------------------------

export type WalletChallengeRequest = { public_address: string }
export type WalletChallengeResponse = {
  challenge_xdr: string
  network_passphrase: string
  expires_at: ISODateTime
}
export type WalletVerifyRequest = { public_address: string; signed_challenge_xdr: string }

// ---------------------------------------------------------------------------
// Bounties
// ---------------------------------------------------------------------------

export type BountyListParams = PageParams & {
  q?: string
  category?: Category
  /** comma separated on the wire */
  skills?: string[]
  /** comma separated on the wire */
  tags?: string[]
  difficulty?: Difficulty
  /** comma separated on the wire */
  status?: BountyStatus[]
  min_reward?: DecimalString
  max_reward?: DecimalString
  deadline_before?: ISODateTime
  deadline_after?: ISODateTime
  funded_only?: boolean
  sort?: BountySort
}

export type MyBountiesParams = PageParams & { role?: 'requester' | 'contributor'; status?: BountyStatus }

export type CreateBountyRequest = {
  title: string
  short_description: string
  description: string
  category: Category
  difficulty: Difficulty
  tags: string[]
  required_skills: string[]
  reward_amount: DecimalString
  reward_asset?: 'XLM'
  application_deadline?: ISODateTime | null
  completion_deadline?: ISODateTime | null
  positions_available: number
  eligibility_criteria?: string | null
  submission_requirements?: string | null
  acceptance_criteria?: string | null
  repository_url?: string | null
  links?: BountyLink[]
  visibility?: Visibility
}

export type UpdateBountyRequest = Partial<CreateBountyRequest>

export type CancelBountyRequest = { reason: string }
export type ReportBountyRequest = { reason: string }
export type ReportCreatedResponse = { id: string }
export type FeatureBountyRequest = { featured: boolean }

// ---------------------------------------------------------------------------
// Applications
// ---------------------------------------------------------------------------

export type CreateApplicationRequest = {
  cover_message: string
  relevant_experience?: string | null
  work_samples?: string[]
}
export type ApplicationListParams = PageParams & { status?: ApplicationStatus }
export type ReviewApplicationRequest = { note?: string }

// ---------------------------------------------------------------------------
// Submissions
// ---------------------------------------------------------------------------

export type CreateSubmissionRequest = {
  description: string
  evidence_url?: string | null
  evidence_links?: string[]
}
export type UpdateSubmissionRequest = Partial<CreateSubmissionRequest>
export type SubmissionListParams = PageParams & { status?: SubmissionStatus }
export type RequestRevisionRequest = { feedback: string }
export type ApproveSubmissionRequest = { feedback?: string }
export type RejectSubmissionRequest = { reason: string }

// ---------------------------------------------------------------------------
// Chain actions / funding / payouts / transactions / payments
// ---------------------------------------------------------------------------

export type ChainPrepareRequest = {
  action: ChainAction
  wallet_address: string
  submission_id?: string
  assignment_id?: string
  dispute_id?: string
  amount?: DecimalString
}
export type FundingPrepareRequest = { wallet_address: string; amount?: DecimalString }
export type PayoutPrepareRequest = { wallet_address: string; submission_id: string }
export type AliasSubmitRequest = { transaction_id: string; signed_xdr: string }
export type TransactionSubmitRequest = { signed_xdr: string }

export type FundingView = {
  funding_status: FundingStatus
  escrow: EscrowView | null
  transactions: BlockchainTransaction[]
}

export type PaymentsParams = PageParams & { direction?: 'received' | 'sent' }

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------

export type NotificationListParams = PageParams & { unread_only?: boolean }
export type NotificationPage = Page<Notification> & { unread_count: number }
export type NotificationChannelPrefs = { in_app: boolean; email: boolean }
export type NotificationPreferences = {
  email_enabled: boolean
  types: Record<NotificationType, NotificationChannelPrefs>
}
export type UpdateNotificationPreferencesRequest = {
  email_enabled?: boolean
  types?: Partial<Record<NotificationType, Partial<NotificationChannelPrefs>>>
}

// ---------------------------------------------------------------------------
// Analytics & dashboard
// ---------------------------------------------------------------------------

export type PublicStats = {
  network: string
  generated_at: ISODateTime
  registered_users: number
  published_bounties: number
  open_bounties: number
  funded_bounties: number
  completed_bounties: number
  verified_payout_volume: DecimalString
  successful_transactions: number
  unique_transacting_wallets: number
  methodology: Record<string, string>
}

export type MonthlyAmount = { month: string; amount: DecimalString }

export type RequesterAnalytics = {
  bounties_by_status: Record<BountyStatus, number>
  total_escrowed: DecimalString
  total_paid: DecimalString
  applications_received: number
  avg_time_to_first_application_hours: number | null
  spending_by_month: MonthlyAmount[]
}

export type ContributorAnalytics = {
  applications_by_status: Record<ApplicationStatus, number>
  submissions_by_status: Record<SubmissionStatus, number>
  total_earned: DecimalString
  earnings_by_month: MonthlyAmount[]
  completed_count: number
}

export type MyAnalytics = { requester: RequesterAnalytics; contributor: ContributorAnalytics }

/** `GET /analytics/platform` (permission analytics:platform) — docs/api.md "Staff response shapes". */
export type PlatformAnalytics = {
  network: string
  generated_at: ISODateTime
  users: {
    registered_users: number
    verified_users: number
    connected_wallets: number
    active_users_30d: number
    /** 0..1 */
    email_verification_rate: number | null
    /** 0..1 */
    wallet_connection_rate: number | null
  }
  bounties: {
    published_bounties: number
    open_bounties: number
    funded_bounties: number
    completed_bounties: number
  }
  transactions: {
    unique_transacting_wallets: number
    successful_transactions: number
    failed_transactions: number
    verified_payout_volume: DecimalString
  }
  engagement: {
    repeat_contributors: number
    applications_decided: number
    /** 0..1 */
    application_acceptance_rate: number | null
    submissions_reviewed: number
    /** 0..1 */
    submission_approval_rate: number | null
  }
  /** Last 30 UTC days, oldest first. */
  time_series: PlatformDay[]
  methodology: Record<string, string>
}

export type PlatformDay = {
  day: string
  registrations: number
  bounties_published: number
  bounties_funded: number
  bounties_completed: number
  applications: number
  submissions: number
  payouts_confirmed_count: number
  payout_volume: DecimalString
}

export type Dashboard = {
  active_bounties: number
  pending_applications_to_review: number
  submissions_awaiting_review: number
  pending_payments: number
  my_pending_applications: number
  my_active_assignments: number
  revision_requests: number
  recent_completed: BountySummary[]
  recent_activity: ActivityItem[]
  recommendations: BountySummary[]
}

// ---------------------------------------------------------------------------
// Disputes
// ---------------------------------------------------------------------------

export type CreateDisputeRequest = {
  reason: string
  evidence_url?: string | null
  /** Required when the requester raises it and several contributors are assigned. */
  contributor_id?: string | null
}
export type AddDisputeEvidenceRequest = { description: string; url?: string | null }
export type ResolveDisputeRequest = { resolution: DisputeResolution; note: string }

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------

/** `GET /admin/overview` (permission system:health) — docs/api.md "Staff response shapes". */
export type AdminOverview = {
  generated_at: ISODateTime
  network: string
  counts: {
    users_total: number
    users_active_30d: number
    users_suspended: number
    bounties_total: number
    bounties_open: number
    bounties_hidden: number
    open_reports: number
    open_disputes: number
    pending_transactions: number
    failed_transactions_24h: number
    unpublished_outbox_events: number
  }
  health: {
    database: HealthCheckState
    redis: HealthCheckState
    kafka: HealthCheckState
    blockchain_rpc: HealthCheckState
    worker: HealthCheckState
  }
  worker_heartbeat_at: ISODateTime | null
}

export type AdminUser = UserSummary & {
  email: string
  role: Role
  is_active: boolean
  email_verified: boolean
  created_at: ISODateTime
}
export type AdminUsersParams = PageParams & { q?: string; role?: Role }
export type AdminUpdateUserRequest = { is_active?: boolean; role?: Role }

export type AdminBountiesParams = PageParams & { q?: string; status?: BountyStatus }
export type ModerationAction = 'HIDE' | 'UNHIDE' | 'CANCEL'
export type ModerateBountyRequest = { action: ModerationAction; reason: string }

export type Report = {
  id: string
  reporter: UserSummary
  target_type: string
  target_id: string
  reason: string
  status: ReportStatus
  created_at: ISODateTime
  resolution_note: string | null
}
export type AdminReportsParams = PageParams & { status?: ReportStatus }
export type ResolveReportRequest = { status: 'ACTIONED' | 'DISMISSED'; note: string }

export type AdminDisputesParams = PageParams & { status?: DisputeStatus }
export type AdminTransactionsParams = PageParams & { status?: TxStatus; type?: TxType }

export type AuditLog = {
  id: string
  actor: UserSummary | null
  action: string
  entity_type: string
  entity_id: string
  metadata: Record<string, unknown>
  created_at: ISODateTime
}
export type AuditLogParams = PageParams & { entity_type?: string; action?: string }
