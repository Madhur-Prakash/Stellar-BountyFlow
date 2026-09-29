import { describe, expect, it } from 'vitest'

import type { SavedSearch, SavedSearchFilters } from '@/lib/api/types'

import { DEFAULT_FILTERS, FOR_YOU, type MarketplaceFilters } from './marketplace-params'
import { reasonText } from './recommendation-reason'
import {
  defaultSearchName,
  describeFilters,
  filtersToSaved,
  sameFilters,
  savedSearchHref,
  savedToFilters,
} from './saved-search-params'

const USDC = 'USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5'

function makeSearch(filters: SavedSearchFilters): SavedSearch {
  return {
    id: 's_1',
    name: 'Rust work',
    filters,
    alert_frequency: 'INSTANT',
    notify_in_app: true,
    notify_email: true,
    is_paused: false,
    new_count: 0,
    last_viewed_at: '2026-09-29T12:00:00Z',
    next_digest_at: null,
    created_at: '2026-09-29T12:00:00Z',
    updated_at: '2026-09-29T12:00:00Z',
  }
}

describe('saved search filters', () => {
  const filters: MarketplaceFilters = {
    ...DEFAULT_FILTERS,
    q: 'soroban',
    category: 'SECURITY',
    difficulty: 'EXPERT',
    status: ['OPEN', 'FUNDED'],
    skills: ['rust', 'wasm'],
    minReward: '100',
    maxReward: '2500',
    deadline: '7d',
    fundedOnly: true,
    asset: USDC,
    sort: 'reward_high',
    page: 3,
  }

  it('snapshots every marketplace filter, with the deadline as a rolling window', () => {
    expect(filtersToSaved(filters)).toEqual({
      q: 'soroban',
      category: ['SECURITY'],
      difficulty: ['EXPERT'],
      status: ['OPEN', 'FUNDED'],
      skills: ['rust', 'wasm'],
      min_reward: '100',
      max_reward: '2500',
      asset: [USDC],
      deadline_within_days: 7,
      funded_only: true,
      sort: 'reward_high',
    })
  })

  it('round-trips back into marketplace filters on the first page', () => {
    const back = savedToFilters(filtersToSaved(filters))
    expect(back).toMatchObject({
      q: 'soroban',
      category: 'SECURITY',
      difficulty: 'EXPERT',
      status: ['OPEN', 'FUNDED'],
      skills: ['rust', 'wasm'],
      deadline: '7d',
      fundedOnly: true,
      asset: USDC,
      sort: 'reward_high',
      page: 1,
    })
    expect(sameFilters(back, filters)).toBe(true)
  })

  it('never saves "for you", which is a personal ranking rather than a list sort', () => {
    expect(filtersToSaved({ ...DEFAULT_FILTERS, sort: FOR_YOU }).sort).toBeUndefined()
    // Switching to "for you" is not a filter change, so it does not ask to update the saved search.
    expect(sameFilters({ ...DEFAULT_FILTERS, sort: FOR_YOU }, DEFAULT_FILTERS)).toBe(true)
  })

  it('notices when the filters have moved away from the saved ones', () => {
    const saved = savedToFilters(filtersToSaved(filters))
    expect(sameFilters(saved, { ...saved, skills: ['rust'] })).toBe(false)
    expect(sameFilters(saved, { ...saved, page: 4 })).toBe(true) // paging is not a filter change
  })

  it('states the reward range in the asset the search filters on', () => {
    expect(describeFilters({ min_reward: '100', max_reward: '2500', asset: [USDC] })).toContain(
      '100 to 2,500 USDC',
    )
    expect(describeFilters({ min_reward: '50', asset: ['native'] })).toContain('At least 50 XLM')
    // Without an asset filter the range covers every asset, so no unit is claimed.
    expect(describeFilters({ min_reward: '50' })).toContain('At least 50')
    expect(describeFilters({ asset: [USDC] })).toContain('Paid in USDC')
  })

  it('describes the rest of a search in plain words', () => {
    expect(describeFilters(filtersToSaved(filters))).toEqual([
      '“soroban”',
      'Security',
      'Expert',
      'Skills: rust, wasm',
      '100 to 2,500 USDC',
      'Closes within 7 days',
      'Funded only',
      'Open, Funded',
    ])
    expect(describeFilters({})).toEqual([])
  })

  it('suggests a name from the most specific thing the search narrows on', () => {
    expect(defaultSearchName({ ...DEFAULT_FILTERS, q: 'soroban audit' })).toBe('soroban audit')
    expect(defaultSearchName({ ...DEFAULT_FILTERS, skills: ['rust', 'wasm'] })).toBe('rust, wasm')
    expect(defaultSearchName({ ...DEFAULT_FILTERS, category: 'DESIGN' })).toBe('Design bounties')
    expect(defaultSearchName({ ...DEFAULT_FILTERS, fundedOnly: true })).toBe('Funded bounties')
    expect(defaultSearchName(DEFAULT_FILTERS)).toBe('All bounties')
  })

  it('links a saved search back to the marketplace it came from', () => {
    const href = savedSearchHref(makeSearch(filtersToSaved(filters)))
    const url = new URL(href, 'http://localhost')
    expect(url.pathname).toBe('/bounties')
    expect(url.searchParams.get('q')).toBe('soroban')
    expect(url.searchParams.get('skills')).toBe('rust,wasm')
    expect(url.searchParams.get('asset')).toBe(USDC)
    expect(url.searchParams.get('saved')).toBe('s_1')
  })
})

describe('recommendation reasons', () => {
  it('names the skills the user already has', () => {
    expect(reasonText({ matched_skills: ['rust', 'soroban'], related_skills: [] })).toBe(
      'Matches rust, soroban',
    )
  })

  it('caps a long list', () => {
    expect(
      reasonText({ matched_skills: ['rust', 'soroban', 'wasm', 'postgresql', 'go'], related_skills: [] }),
    ).toBe('Matches rust, soroban, wasm and 2 more')
  })

  it('falls back to the skill the match was reached through', () => {
    expect(
      reasonText({
        matched_skills: [],
        related_skills: [
          { skill: 'webassembly', via: 'soroban' },
          { skill: 'stellar', via: 'soroban' },
        ],
      }),
    ).toBe('Related to soroban')
  })

  it('says nothing when there is no reason to give', () => {
    expect(reasonText({ matched_skills: [], related_skills: [] })).toBeNull()
    expect(reasonText(null)).toBeNull()
  })
})
