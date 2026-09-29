import { format, formatDistanceToNowStrict, isValid, parseISO } from 'date-fns'

import type {
  ApplicationStatus,
  BountyStatus,
  Category,
  Difficulty,
  DisputeStatus,
  FundingStatus,
  PaymentStatus,
  ReportStatus,
  SubmissionStatus,
  TxStatus,
  TxType,
} from '@/lib/api/types'

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const d = parseISO(iso)
  return isValid(d) ? d : null
}

/** "Sep 25, 2026" */
export function formatDate(iso: string | null | undefined): string {
  const d = toDate(iso)
  return d ? format(d, 'MMM d, yyyy') : '—'
}

/** "Sep 25, 2026, 14:05" (local time) */
export function formatDateTime(iso: string | null | undefined): string {
  const d = toDate(iso)
  return d ? format(d, 'MMM d, yyyy, HH:mm') : '—'
}

/** "3 hours ago" / "in 2 days" */
export function formatRelative(iso: string | null | undefined): string {
  const d = toDate(iso)
  return d ? formatDistanceToNowStrict(d, { addSuffix: true }) : '—'
}

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return new Intl.NumberFormat('en-US').format(n)
}

/** 0..1 ratio → "72%" ; null → "—" */
export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '—'
  return `${Math.round(ratio * 100)}%`
}

/** SCREAMING_SNAKE → "Screaming snake" */
export function humanize(value: string): string {
  const s = value.replace(/_/g, ' ').toLowerCase()
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export const CATEGORY_LABELS: Record<Category, string> = {
  DEVELOPMENT: 'Development',
  BUG_BOUNTY: 'Bug bounty',
  DESIGN: 'Design',
  SECURITY: 'Security',
  DOCUMENTATION: 'Documentation',
  RESEARCH: 'Research',
  COMMUNITY: 'Community',
  OTHER: 'Other',
}

export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  BEGINNER: 'Beginner',
  INTERMEDIATE: 'Intermediate',
  ADVANCED: 'Advanced',
  EXPERT: 'Expert',
}

export const BOUNTY_STATUS_LABELS: Record<BountyStatus, string> = {
  DRAFT: 'Draft',
  OPEN: 'Open',
  FUNDING_PENDING: 'Funding pending',
  FUNDED: 'Funded',
  IN_PROGRESS: 'In progress',
  UNDER_REVIEW: 'Under review',
  COMPLETED: 'Completed',
  CANCEL_REQUESTED: 'Cancel requested',
  CANCELLED: 'Cancelled',
  DISPUTED: 'Disputed',
  EXPIRED: 'Expired',
}

export const FUNDING_STATUS_LABELS: Record<FundingStatus, string> = {
  UNFUNDED: 'Unfunded',
  PENDING: 'Funding pending',
  PARTIALLY_FUNDED: 'Partially funded',
  FUNDED: 'Funded in escrow',
  REFUND_PENDING: 'Refund pending',
  REFUNDED: 'Refunded',
  SETTLED: 'Settled',
}

export const APPLICATION_STATUS_LABELS: Record<ApplicationStatus, string> = {
  PENDING: 'Pending',
  ACCEPTED: 'Accepted',
  REJECTED: 'Rejected',
  WITHDRAWN: 'Withdrawn',
}

export const SUBMISSION_STATUS_LABELS: Record<SubmissionStatus, string> = {
  SUBMITTED: 'Submitted',
  REVISION_REQUESTED: 'Revision requested',
  RESUBMITTED: 'Resubmitted',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
}

export const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = {
  NOT_REQUIRED: 'Not required',
  CREATED: 'Awaiting payout',
  SIGNATURE_REQUIRED: 'Signature required',
  SUBMITTED: 'Submitted',
  CONFIRMED: 'Confirmed',
  FAILED: 'Failed',
  REFUND_PENDING: 'Refund pending',
  REFUNDED: 'Refunded',
}

export const TX_STATUS_LABELS: Record<TxStatus, string> = {
  CREATED: 'Created',
  SIGNATURE_REQUIRED: 'Signature required',
  SUBMITTED: 'Submitted',
  CONFIRMED: 'Confirmed',
  FAILED: 'Failed',
  EXPIRED: 'Expired',
}

export const TX_TYPE_LABELS: Record<TxType, string> = {
  ESCROW_CREATE: 'Escrow created',
  ESCROW_FUND: 'Escrow funded',
  ASSIGN: 'Contributor assigned',
  PAYOUT: 'Payout',
  CANCEL_REQUEST: 'Cancel requested',
  CANCEL_CONSENT: 'Cancel consent',
  REFUND: 'Refund',
  DISPUTE_RAISE: 'Dispute raised',
  DISPUTE_RESOLVE: 'Dispute resolved',
  WALLET_CHALLENGE: 'Wallet verification',
  MILESTONE_PAYOUT: 'Milestone payout',
  BATCH_PAYOUT: 'Batch payout',
  SUBMIT_WORK: 'Work recorded',
  REQUEST_CHANGES: 'Changes requested',
  REJECT_SUBMISSION: 'Work rejected',
  CLAIM: 'Payment claimed',
  DISPUTE_VOTE: 'Arbiter vote',
}

export const DISPUTE_STATUS_LABELS: Record<DisputeStatus, string> = {
  OPEN: 'Open',
  UNDER_REVIEW: 'Under review',
  RESOLVED: 'Resolved',
  DISMISSED: 'Dismissed',
}

export const REPORT_STATUS_LABELS: Record<ReportStatus, string> = {
  OPEN: 'Open',
  REVIEWING: 'Reviewing',
  ACTIONED: 'Actioned',
  DISMISSED: 'Dismissed',
}

/**
 * Readable phrase for an activity/audit action code ("submission.approved",
 * "bounty.funded", …). `withTitle` reads naturally when the bounty title
 * follows ("approved work on …"); `standalone` is for per-bounty feeds.
 */
const ACTIVITY_PHRASES: Record<string, [withTitle: string, standalone: string]> = {
  'bounty.created': ['created', 'created the bounty'],
  'bounty.updated': ['updated', 'updated the bounty'],
  'bounty.featured': ['featured', 'featured the bounty'],
  'bounty.moderated.hide': ['hid', 'hid the bounty from the marketplace'],
  'bounty.moderated.unhide': ['unhid', 'made the bounty visible again'],
  'bounty.moderated.cancel': ['cancelled (moderation)', 'cancelled the bounty (moderation)'],
  'bounty.open': ['published', 'published the bounty'],
  'bounty.funding_pending': ['submitted escrow funding for', 'submitted escrow funding'],
  'bounty.funded': ['funded the escrow for', 'funded the escrow'],
  'bounty.cancel_requested': ['requested cancellation of', 'requested cancellation'],
  'bounty.cancelled': ['cancelled', 'cancelled the bounty'],
  'bounty.completed': ['completed', 'completed the bounty'],
  'bounty.expired': ['saw the deadline pass on', 'saw the deadline pass'],
  'application.created': ['applied to', 'applied'],
  'application.accepted': ['accepted an applicant on', 'accepted an applicant'],
  'application.rejected': ['declined an applicant on', 'declined an applicant'],
  'application.withdrawn': ['withdrew from', 'withdrew an application'],
  'submission.created': ['submitted work on', 'submitted work'],
  'submission.resubmitted': ['sent a revision for', 'sent a revision'],
  'submission.revision_requested': ['requested changes on', 'requested changes'],
  'submission.approved': ['approved work on', 'approved the work'],
  'submission.rejected': ['rejected work on', 'rejected the work'],
  'transaction.submitted': ['submitted a transaction for', 'submitted a transaction'],
  'transaction.confirmed': ['confirmed a transaction on Stellar for', 'confirmed a transaction on Stellar'],
  'transaction.failed': ['had a transaction fail for', 'had a transaction fail'],
  'payment.confirmed': ['paid out the reward for', 'paid out the reward'],
  'dispute.raised': ['raised a dispute on', 'raised a dispute'],
  'dispute.assigned': ['took the dispute on', 'took the dispute for review'],
  'dispute.evidence_added': ['added dispute evidence on', 'added dispute evidence'],
  'dispute.resolved': ['resolved the dispute on', 'resolved the dispute'],
  'report.created': ['reported', 'reported the bounty'],
}

export function describeActivity(action: string, withTitle = false): string {
  const known = ACTIVITY_PHRASES[action]
  if (known) return withTitle ? known[0] : known[1]
  const status = /^bounty\.([a-z_]+)$/.exec(action)?.[1]?.toUpperCase()
  if (status && status in BOUNTY_STATUS_LABELS) {
    const label = BOUNTY_STATUS_LABELS[status as BountyStatus]
    return withTitle ? `moved to ${label}:` : `moved the bounty to ${label}`
  }
  return humanize(action.replaceAll('.', ' ')).toLowerCase()
}
