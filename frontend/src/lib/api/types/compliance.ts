/** Privacy (data export, account deletion), legal document versions, sanctions screening and ops status. */

type ISODateTime = string
type UserRef = { id: string; username: string; display_name: string; avatar_url: string | null }

// ---------------------------------------------------------------------------
// Data export
// ---------------------------------------------------------------------------

export const EXPORT_STATUSES = ['PENDING', 'PROCESSING', 'READY', 'FAILED', 'EXPIRED'] as const
export type ExportStatus = (typeof EXPORT_STATUSES)[number]

export type DataExport = {
  id: string
  status: ExportStatus
  created_at: ISODateTime
  completed_at: ISODateTime | null
  expires_at: ISODateTime | null
  size_bytes: number | null
  download_count: number
  /** API path of a signed link valid for a few minutes (READY only). Fetch the list again for a fresh one. */
  download_url: string | null
}

// ---------------------------------------------------------------------------
// Account deletion
// ---------------------------------------------------------------------------

export const DELETION_STATUSES = ['SCHEDULED', 'CANCELLED', 'COMPLETED'] as const
export type DeletionStatus = (typeof DELETION_STATUSES)[number]

export type DeletionBlocker = { kind: string; message: string; count: number; links: string[] }

export type DeletionRequest = {
  id: string
  status: DeletionStatus
  created_at: ISODateTime
  scheduled_for: ISODateTime
  cancelled_at: ISODateTime | null
  completed_at: ISODateTime | null
  blocked_reason: string | null
}

export type DeletionState = {
  request: DeletionRequest | null
  blockers: DeletionBlocker[]
  grace_days: number
}

export type RequestDeletionBody = { password: string; reason?: string }

export type AdminDeletionRequest = DeletionRequest & {
  user: UserRef
  email: string
  reason: string | null
  pseudonym: string | null
  last_attempt_at: ISODateTime | null
  blockers: DeletionBlocker[]
}
export type AdminDeletionParams = { page?: number; page_size?: number; status?: DeletionStatus }

// ---------------------------------------------------------------------------
// Legal documents
// ---------------------------------------------------------------------------

export const LEGAL_DOCUMENTS = ['TERMS', 'PRIVACY'] as const
export type LegalDocument = (typeof LEGAL_DOCUMENTS)[number]

export type LegalVersion = {
  id: string
  document: LegalDocument
  version: string
  summary: string
  effective_at: ISODateTime
  created_at: ISODateTime
  withdrawn_at: ISODateTime | null
}

export type LegalDocumentStatus = {
  document: LegalDocument
  current: LegalVersion | null
  upcoming: LegalVersion | null
  accepted_current: boolean
  accepted_upcoming: boolean
  accepted_at: ISODateTime | null
}

export type LegalStatus = {
  documents: LegalDocumentStatus[]
  needs_acceptance: boolean
  upcoming_pending: boolean
}

export type AdminLegalVersion = LegalVersion & { published_by: UserRef | null; accepted_count: number }
export type PublishLegalVersionBody = {
  document: LegalDocument
  version: string
  summary: string
  effective_at?: ISODateTime
}

// ---------------------------------------------------------------------------
// Screening
// ---------------------------------------------------------------------------

export type ScreeningSource = 'LIST' | 'MANUAL'

export type ScreeningEntry = {
  id: string
  address: string
  source: ScreeningSource
  list_name: string
  reason: string | null
  created_at: ISODateTime
  added_by: UserRef | null
  removed_at: ISODateTime | null
  removal_note: string | null
}
export type ScreeningEntryParams = {
  page?: number
  page_size?: number
  q?: string
  source?: ScreeningSource
  include_removed?: boolean
}

export type ScreeningMatch = {
  entry_id: string
  source: ScreeningSource
  list_name: string
  reason: string | null
}

export type ScreeningDecision = {
  id: string
  created_at: ISODateTime
  result: 'blocked' | 'cleared'
  address: string
  context: string
  provider: string
  user: UserRef | null
  matches: ScreeningMatch[]
  bounty_id: string | null
  request_id: string | null
}
export type ScreeningDecisionParams = {
  page?: number
  page_size?: number
  result?: 'blocked' | 'cleared'
  q?: string
}

export type ScreeningStatus = {
  enabled: boolean
  provider: string
  manual_entries: number
  list_entries: number
  list: {
    configured: boolean
    name: string
    source: string | null
    format: string | null
    entries: number
    loaded_at: ISODateTime | null
    checked_at: ISODateTime | null
    error: string | null
  }
}
