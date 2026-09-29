/**
 * Escrow v2: milestones, the on-chain review clock, the M-of-N arbiter panel and the escrow settings
 * (docs/api.md, "Escrow v2"). Re-exported from `../types`.
 */
import type { DecimalString, ISODateTime, UserSummary } from '../types'

export const MILESTONE_STATUSES = ['OPEN', 'PAID', 'SETTLED'] as const
export type MilestoneStatus = (typeof MILESTONE_STATUSES)[number]

export type Milestone = {
  id: string
  /** Index of the milestone in the escrow contract. */
  position: number
  title: string
  description: string | null
  amount: DecimalString
  /** PAID / SETTLED only after the payout was verified on-chain. */
  status: MilestoneStatus
  paid_at: ISODateTime | null
  payout_transaction_id: string | null
  explorer_url: string | null
}

export type MilestoneInput = { title: string; description?: string | null; amount: DecimalString }

/** The milestone a submission is for. */
export type SubmissionMilestone = Pick<Milestone, 'id' | 'position' | 'title' | 'amount' | 'status'>

export const ONCHAIN_REVIEW_STATES = ['PENDING', 'CHANGES_REQUESTED', 'REJECTED', 'PAID'] as const
export type OnchainReviewState = (typeof ONCHAIN_REVIEW_STATES)[number]

/** The contract's review clock for one submission (from verified chain state). */
export type OnchainReview = {
  state: OnchainReviewState
  submitted_at: ISODateTime | null
  /** When the contributor can claim if the requester has not answered. */
  claimable_at: ISODateTime | null
  can_claim: boolean
  can_answer: boolean
}

export type EscrowConfig = {
  contract_id: string | null
  contract_version: number
  default_review_window_seconds: number
  min_review_window_seconds: number
  max_review_window_seconds: number
  arbiter_addresses: string[]
  arbiter_threshold: number
  max_milestones: number
  max_batch: number
}

export type ArbiterView = {
  address: string
  /** The staff account that verified this arbiter wallet. */
  staff: UserSummary | null
  approved: boolean
  contributor_amount: DecimalString | null
}

export type Arbitration = {
  dispute_id: string
  contract_version: number
  escrow_frozen: boolean
  executed: boolean
  round: number
  threshold: number
  approvals: number
  arbiters: ArbiterView[]
  resolution: string | null
  contributor_amount: DecimalString | null
  requester_amount: DecimalString | null
  position_value: DecimalString | null
  my_arbiter_wallets: string[]
  my_vote_recorded: boolean
  can_vote: boolean
  vote_blocked_reason: string | null
}
