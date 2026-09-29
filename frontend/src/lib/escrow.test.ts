import { describe, expect, it } from 'vitest'

import type { Dispute } from '@/lib/api/types'

import {
  approvalsLabel,
  DAY_SECONDS,
  formatWindow,
  needsArbiterVotes,
  splitWindow,
  sumMilestones,
  toSeconds,
  windowUnits,
} from './escrow'

describe('formatWindow', () => {
  it('uses the largest whole unit', () => {
    expect(formatWindow(7 * DAY_SECONDS)).toBe('7 days')
    expect(formatWindow(DAY_SECONDS)).toBe('1 day')
    expect(formatWindow(36 * 3600)).toBe('36 hours')
    expect(formatWindow(60)).toBe('1 minute')
    expect(formatWindow(90 * 60)).toBe('90 minutes')
  })

  it('renders a dash for a missing window', () => {
    expect(formatWindow(null)).toBe('—')
    expect(formatWindow(0)).toBe('—')
  })
})

describe('splitWindow / toSeconds', () => {
  it('round-trips the form inputs', () => {
    for (const seconds of [60, 45 * 60, 3600, 36 * 3600, DAY_SECONDS, 30 * DAY_SECONDS]) {
      const { value, unit } = splitWindow(seconds)
      expect(toSeconds(value, unit)).toBe(seconds)
    }
    expect(splitWindow(7 * DAY_SECONDS)).toEqual({ value: 7, unit: 'days' })
  })
})

describe('windowUnits', () => {
  it('offers minutes only when the server allows windows under an hour', () => {
    expect(windowUnits(60)).toEqual(['minutes', 'hours', 'days'])
    expect(windowUnits(3600)).toEqual(['hours', 'days'])
    expect(windowUnits(DAY_SECONDS)).toEqual(['days'])
  })
})

describe('sumMilestones', () => {
  it('adds decimal amounts exactly, in stroops', () => {
    expect(sumMilestones(['0.1', '0.2'])).toBe(3_000_000n)
    expect(sumMilestones(['1', '2.5'])).toBe(35_000_000n)
  })

  it('refuses an empty, zero or invalid amount', () => {
    expect(sumMilestones(['1', ''])).toBeNull()
    expect(sumMilestones(['1', '0'])).toBeNull()
    expect(sumMilestones(['1', '1.12345678'])).toBeNull()
  })
})

function dispute(overrides: Partial<Dispute>): Dispute {
  return {
    id: 'd1',
    bounty: { id: 'b1', slug: 'b', title: 'Bounty' },
    raised_by: { id: 'u1', username: 'ada', display_name: 'Ada', avatar_url: null },
    reason: 'reason',
    status: 'RESOLVED',
    assigned_moderator: null,
    resolution: 'RELEASE_TO_CONTRIBUTOR',
    resolution_note: null,
    evidence: [],
    created_at: '2026-09-29T00:00:00Z',
    resolved_at: null,
    ...overrides,
  } as Dispute
}

describe('needsArbiterVotes', () => {
  it('keeps the single-arbiter path for v1 escrows and 1-of-1 release or refund', () => {
    expect(needsArbiterVotes(dispute({ contract_version: 1, arbiter_threshold: 1 }))).toBe(false)
    expect(needsArbiterVotes(dispute({ contract_version: 2, arbiter_threshold: 1 }))).toBe(false)
    expect(needsArbiterVotes(dispute({}))).toBe(false)
  })

  it('uses votes for an M-of-N set or a split', () => {
    expect(needsArbiterVotes(dispute({ contract_version: 2, arbiter_threshold: 2 }))).toBe(true)
    expect(
      needsArbiterVotes(dispute({ contract_version: 2, arbiter_threshold: 1, resolution: 'SPLIT' })),
    ).toBe(true)
  })
})

describe('approvalsLabel', () => {
  it('counts verified approvals against the threshold', () => {
    expect(approvalsLabel({ arbiter_approvals: 1, arbiter_threshold: 2 })).toBe('1 of 2 approvals')
    expect(approvalsLabel({})).toBe('0 of 1 approval')
  })
})
