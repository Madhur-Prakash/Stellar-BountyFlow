import type { Asset, AssetAmount, DecimalString, ISODateTime, UserSummary } from '../types'

// ---------------------------------------------------------------------------
// On-chain completion attestations (contracts/attestations)
// ---------------------------------------------------------------------------

export type AttestationStatus = 'PENDING' | 'SUBMITTED' | 'CONFIRMED' | 'REVOKING' | 'REVOKED' | 'FAILED'

/**
 * One completed (bounty, contributor) pair recorded in the on-chain registry. `amount` is everything the
 * contributor was paid on that bounty, in the bounty's reward asset, however many transfers paid it
 * (`payments_count`): a release, milestone payouts, a batch leg or a claim.
 */
export type Attestation = {
  id: string
  /** Id in the on-chain registry (null until it is recorded). */
  onchain_id: number | null
  status: AttestationStatus
  network: string
  contributor: UserSummary
  contributor_address: string
  bounty: { id: string; slug: string; title: string }
  amount: DecimalString
  asset: Asset
  payments_count: number
  first_paid_at: ISODateTime | null
  completed_at: ISODateTime
  attested_at: ISODateTime | null
  confirmed_at: ISODateTime | null
  payout_tx_hash: string
  payout_explorer_url: string | null
  attestation_tx_hash: string | null
  attestation_explorer_url: string | null
  contract_id: string
  contract_explorer_url: string
  escrow_contract_id: string
  onchain_bounty_id: string
  token_contract_id: string
  revoked_at: ISODateTime | null
  revocation_reason: string | null
}

/** The record as read from the contract when the page was requested. */
export type AttestationChainRead = {
  checked_at: ISODateTime
  found: boolean
  matches: boolean
  revoked: boolean
  record: Record<string, unknown> | null
  error: string | null
}

export type AttestationDetail = Attestation & { chain: AttestationChainRead | null }

export type ReputationSummary = {
  /** False when the attestation registry is not configured on this server. */
  enabled: boolean
  attested_completions: number
  revoked: number
  earned: AssetAmount[]
  first_completed_at: ISODateTime | null
  last_completed_at: ISODateTime | null
  network: string
  contract_id: string | null
  contract_explorer_url: string | null
  attester_address: string | null
}

export type MyAttestationCounts = { confirmed: number; in_progress: number; revoked: number; failed: number }

// ---------------------------------------------------------------------------
// Verifiable credentials (W3C VC 2.0, eddsa-jcs-2022)
// ---------------------------------------------------------------------------

export type CredentialKind = 'COMPLETION' | 'SUMMARY'

export type IssuerInfo = {
  enabled: boolean
  did: string | null
  verification_method: string | null
  did_document_url: string | null
  status_list_url: string | null
  cryptosuite: string
}

export type CredentialRecord = {
  id: string
  credential_id: string
  kind: CredentialKind
  attestation_id: string | null
  attestation_count: number
  subject_did: string
  issuer_did: string
  issued_at: ISODateTime
  revoked_at: ISODateTime | null
  revocation_reason: string | null
}

export type VerifiableCredential = Record<string, unknown>

export type IssuedCredential = CredentialRecord & { document: VerifiableCredential }

export type VerificationCheckId = 'format' | 'issuer' | 'signature' | 'validity' | 'status' | 'attestation'

export type VerificationCheck = {
  id: VerificationCheckId
  label: string
  status: 'pass' | 'fail' | 'skip'
  detail: string
}

export type VerifiedAttestation = {
  onchain_id: number
  contract_id: string
  matches: boolean
  revoked: boolean
  detail: string
  attestation_path: string | null
  explorer_url: string | null
  contract_explorer_url: string
}

export type VerificationReport = {
  verified: boolean
  checks: VerificationCheck[]
  credential_id: string | null
  kind: 'completion' | 'summary' | null
  issuer: { id: string | null; name: string | null; is_this_site: boolean }
  subject: string | null
  valid_from: string | null
  attestations: VerifiedAttestation[]
  checked_at: ISODateTime
}
