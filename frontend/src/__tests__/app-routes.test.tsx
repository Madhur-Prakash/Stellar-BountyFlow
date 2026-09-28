import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { qk } from '@/lib/api/queries/keys'
import { routes } from '@/router'
import { jsonResponse, makeConfig } from '@/test/fixtures'
import { createTestQueryClient } from '@/test/render'

const fetchMock = vi.fn<(input: string, init: RequestInit) => Promise<Response>>()

function renderAt(url: string) {
  const client = createTestQueryClient()
  client.setQueryData(qk.config, makeConfig())
  client.setQueryData(qk.auth.me, null)
  const router = createMemoryRouter(routes, { initialEntries: [url] })
  render(
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return router
}

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockImplementation(async (url) => {
    if (url.includes('/bounties/featured')) return jsonResponse([])
    if (url.includes('/analytics/public'))
      return jsonResponse({
        network: 'testnet',
        generated_at: '2026-09-25T12:00:00Z',
        registered_users: 0,
        published_bounties: 0,
        open_bounties: 0,
        funded_bounties: 0,
        completed_bounties: 0,
        verified_payout_volume: '0.0000000',
        successful_transactions: 0,
        unique_transacting_wallets: 0,
        methodology: {},
      })
    if (url.includes('/bounties/featured')) return jsonResponse([])
    if (url.includes('/bounties'))
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 12, pages: 0 })
    return jsonResponse({ error: { code: 'not_found', message: 'Not found' } }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('app routes (lazy modules, real layouts)', () => {
  it('renders the landing page with honest empty states', async () => {
    renderAt('/')
    expect(await screen.findByRole('heading', { level: 1 }, { timeout: 15000 })).toHaveTextContent(
      'Work gets done.',
    )
    expect(await screen.findByText('No open bounties right now.')).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Post the first bounty' })).toBeInTheDocument()
    expect(screen.getByText(/Network: Testnet/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /skip to content/i })).toBeInTheDocument()
  }, 30_000)

  it('renders the marketplace empty state', async () => {
    renderAt('/bounties')
    expect(await screen.findByText('No open bounties yet', undefined, { timeout: 15000 })).toBeInTheDocument()
  }, 30_000)

  it('shows the 404 page for unknown routes', async () => {
    renderAt('/definitely-not-here')
    expect(
      await screen.findByRole('heading', { name: /page not found/i }, { timeout: 15000 }),
    ).toBeInTheDocument()
  }, 30_000)

  it('redirects anonymous visitors from /app to /login with a return URL', async () => {
    const router = renderAt('/app/saved')
    expect(
      await screen.findByRole('heading', { name: /sign in to bountyflow/i }, { timeout: 15000 }),
    ).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/login')
    expect(router.state.location.search).toBe('?next=%2Fapp%2Fsaved')
  }, 30_000)
})
