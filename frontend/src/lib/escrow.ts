/**
 * Escrow v2 display helpers: review-window durations, milestone and review-clock labels.
 */
import type { Dispute, MilestoneStatus, OnchainReviewState } from '@/lib/api/types'
import { tryParseAmount } from '@/lib/money'

export const DAY_SECONDS = 86_400

export type WindowUnit = 'minutes' | 'hours' | 'days'

const UNIT_SECONDS: Record<WindowUnit, number> = { minutes: 60, hours: 3600, days: DAY_SECONDS }

/** "7 days", "36 hours", "2 minutes". */
export function formatWindow(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return '—'
  if (seconds % DAY_SECONDS === 0) {
    const d = seconds / DAY_SECONDS
    return `${d} day${d === 1 ? '' : 's'}`
  }
  if (seconds % 3600 === 0) {
    const h = seconds / 3600
    return `${h} hour${h === 1 ? '' : 's'}`
  }
  const m = Math.round(seconds / 60)
  return `${m} minute${m === 1 ? '' : 's'}`
}

/** Seconds → the largest whole unit (for the form's number + unit inputs). */
export function splitWindow(seconds: number): { value: number; unit: WindowUnit } {
  if (seconds % DAY_SECONDS === 0) return { value: seconds / DAY_SECONDS, unit: 'days' }
  if (seconds % 3600 === 0) return { value: seconds / 3600, unit: 'hours' }
  return { value: Math.max(1, Math.round(seconds / 60)), unit: 'minutes' }
}

export function toSeconds(value: number, unit: WindowUnit): number {
  return Math.round(value * UNIT_SECONDS[unit])
}

/** Units a requester can pick: minutes only exist when the server allows windows under an hour (test stacks). */
export function windowUnits(minSeconds: number): WindowUnit[] {
  if (minSeconds < 3600) return ['minutes', 'hours', 'days']
  if (minSeconds < DAY_SECONDS) return ['hours', 'days']
  return ['days']
}

export const MILESTONE_STATUS_LABELS: Record<MilestoneStatus, string> = {
  OPEN: 'Open',
  PAID: 'Paid',
  SETTLED: 'Settled by dispute',
}

export const ONCHAIN_REVIEW_LABELS: Record<OnchainReviewState, string> = {
  PENDING: 'Review clock running',
  CHANGES_REQUESTED: 'Changes requested on-chain',
  REJECTED: 'Rejected on-chain',
  PAID: 'Paid on-chain',
}

/** Sum of decimal strings in stroops, or null when one of them is not a valid amount. */
export function sumMilestones(amounts: string[]): bigint | null {
  let total = 0n
  for (const raw of amounts) {
    const v = tryParseAmount(raw)
    if (v === null || v <= 0n) return null
    total += v
  }
  return total
}

/**
 * A frozen v2 escrow is executed by arbiter votes when it needs more than one approval, or when the decision
 * splits the reward (the single-arbiter RESOLVE_DISPUTE call can only release or refund in full).
 */
export function needsArbiterVotes(d: Dispute): boolean {
  return (d.contract_version ?? 1) >= 2 && ((d.arbiter_threshold ?? 1) > 1 || d.resolution === 'SPLIT')
}

/** "2 of 3 approvals" from the dispute list row (verified votes only). */
export function approvalsLabel(d: Pick<Dispute, 'arbiter_approvals' | 'arbiter_threshold'>): string {
  const threshold = d.arbiter_threshold ?? 1
  return `${d.arbiter_approvals ?? 0} of ${threshold} approval${threshold === 1 ? '' : 's'}`
}
