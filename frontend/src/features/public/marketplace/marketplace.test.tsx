import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { BountyFilters } from '@/components/bounty/BountyFilters'
import { jsonResponse, makeBounty } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'

import {
  DEFAULT_FILTERS,
  activeFilterCount,
  effectiveSort,
  parseFilters,
  serializeFilters,
  toApiParams,
} from './marketplace-params'
import MarketplacePage from './MarketplacePage'

describe('marketplace URL params', () => {
  it('round-trips filters through the URL', () => {
    const filters = {
      ...DEFAULT_FILTERS,
      q: 'soroban',
      category: 'SECURITY' as const,
      difficulty: 'EXPERT' as const,
      status: ['OPEN', 'FUNDED'] as ('OPEN' | 'FUNDED')[],
      skills: ['rust', 'wasm'],
      minReward: '100',
      maxReward: '2500.5',
      deadline: '7d' as const,
      fundedOnly: true,
      sort: 'reward_high' as const,
      page: 3,
    }
    const sp = serializeFilters(filters)
    expect(sp.toString()).toBe(
      'q=soroban&category=SECURITY&difficulty=EXPERT&status=OPEN%2CFUNDED&skills=rust%2Cwasm&min_reward=100&max_reward=2500.5&deadline=7d&funded_only=true&sort=reward_high&page=3',
    )
    expect(parseFilters(sp)).toEqual(filters)
  })

  it('drops invalid values instead of sending them to the API', () => {
    const f = parseFilters(
      new URLSearchParams(
        'category=NOPE&status=DRAFT,OPEN,BOGUS&min_reward=-5&max_reward=1.123456789&sort=hot&page=-2&deadline=1y',
      ),
    )
    expect(f.category).toBeNull()
    expect(f.status).toEqual(['OPEN'])
    expect(f.minReward).toBe('')
    expect(f.maxReward).toBe('')
    expect(f.sort).toBeNull()
    expect(f.page).toBe(1)
    expect(f.deadline).toBeNull()
  })

  it('omits defaults from the URL', () => {
    expect(serializeFilters(DEFAULT_FILTERS).toString()).toBe('')
  })

  it('defaults to relevance while searching and newest otherwise', () => {
    expect(effectiveSort({ q: '', sort: null })).toBe('newest')
    expect(effectiveSort({ q: 'rust', sort: null })).toBe('relevance')
    expect(effectiveSort({ q: '', sort: 'relevance' })).toBe('newest')
    expect(effectiveSort({ q: 'rust', sort: 'popular' })).toBe('popular')
  })

  it('maps filters to API params with a stable deadline window', () => {
    const now = new Date('2026-09-25T10:15:42Z')
    const p = toApiParams({ ...DEFAULT_FILTERS, deadline: '3d', fundedOnly: true, skills: ['go'] }, now)
    expect(p).toMatchObject({
      sort: 'newest',
      page: 1,
      page_size: 12,
      funded_only: true,
      skills: ['go'],
      deadline_after: '2026-09-25T10:15:00.000Z',
      deadline_before: '2026-09-28T10:15:00.000Z',
    })
    expect(activeFilterCount({ ...DEFAULT_FILTERS, deadline: '3d', fundedOnly: true, skills: ['go'] })).toBe(
      3,
    )
  })
})

describe('BountyFilters', () => {
  it('emits a page reset with each change', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderWithProviders(<BountyFilters filters={DEFAULT_FILTERS} onChange={onChange} />)
    await user.click(await screen.findByRole('switch', { name: /funded only/i }))
    expect(onChange).toHaveBeenLastCalledWith({ fundedOnly: true, page: 1 })
    await user.click(screen.getByRole('checkbox', { name: 'Under review' }))
    expect(onChange).toHaveBeenLastCalledWith({ status: ['UNDER_REVIEW'], page: 1 })
    await user.click(screen.getByRole('radio', { name: 'Within 7 days' }))
    expect(onChange).toHaveBeenLastCalledWith({ deadline: '7d', page: 1 })
  })

  it('validates the reward range', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderWithProviders(<BountyFilters filters={DEFAULT_FILTERS} onChange={onChange} />)
    await user.type(await screen.findByLabelText('Min'), '500')
    await user.type(screen.getByLabelText('Max'), '100')
    await user.tab()
    expect(await screen.findByText('Minimum must not exceed maximum.')).toBeInTheDocument()
    // The valid minimum is committed on blur; the invalid range is never emitted.
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ maxReward: '100' }))
  })
})

describe('MarketplacePage URL sync', () => {
  const fetchMock = vi.fn<(input: string, init: RequestInit) => Promise<Response>>()
  beforeEach(() => {
    fetchMock.mockReset()
    fetchMock.mockImplementation(async () =>
      jsonResponse({ items: [makeBounty()], total: 1, page: 1, page_size: 12, pages: 1 }),
    )
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('reads filters from the URL into the API request', async () => {
    renderWithProviders(<MarketplacePage />, {
      route: '/bounties?q=indexer&funded_only=true&category=DEVELOPMENT',
      path: '/bounties',
      me: null,
    })
    expect(await screen.findByRole('heading', { level: 1, name: /bounty marketplace/i })).toBeInTheDocument()
    await screen.findByRole('article', { name: /soroban event indexer/i })
    const url = new URL(fetchMock.mock.calls[0]![0], 'http://localhost')
    expect(url.pathname).toBe('/api/v1/bounties')
    expect(url.searchParams.get('q')).toBe('indexer')
    expect(url.searchParams.get('funded_only')).toBe('true')
    expect(url.searchParams.get('category')).toBe('DEVELOPMENT')
    expect(url.searchParams.get('sort')).toBe('relevance')
    expect(screen.getByRole('searchbox', { name: /search bounties/i })).toHaveValue('indexer')
  })

  it('writes debounced search and filter changes back to the URL', async () => {
    const user = userEvent.setup()
    const { router } = renderWithProviders(<MarketplacePage />, {
      route: '/bounties',
      path: '/bounties',
      me: null,
    })
    await screen.findByRole('article')

    await user.type(screen.getByRole('searchbox', { name: /search bounties/i }), 'rust')
    await waitFor(() => expect(router.state.location.search).toBe('?q=rust'), { timeout: 2000 })
    // Wait for the page to re-render with the new URL before the next interaction.
    expect(await screen.findByText(/for “rust”/)).toBeInTheDocument()

    const filters = screen.getByRole('complementary', { name: /bounty filters/i })
    await user.click(within(filters).getByRole('switch', { name: /funded only/i }))
    await waitFor(() => expect(router.state.location.search).toBe('?q=rust&funded_only=true'))
  })
})
