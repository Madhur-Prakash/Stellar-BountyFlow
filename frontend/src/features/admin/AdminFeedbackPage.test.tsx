import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Feedback, FeedbackPage } from '@/lib/api/types'
import { jsonResponse, makeMe } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'

import AdminFeedbackPage from './AdminFeedbackPage'

const fromAccount: Feedback = {
  id: 'f_1',
  kind: 'BUG',
  status: 'NEW',
  message: 'The funding progress bar stays at zero after the escrow confirms.',
  sender: { id: 'u_2', username: 'grace', display_name: 'Grace Hopper', avatar_url: null },
  email: null,
  path: '/bounties/escrow-widget',
  viewport_width: 1280,
  viewport_height: 800,
  user_agent: 'Mozilla/5.0 (Macintosh) Chrome/141.0 Safari/537.36',
  created_at: '2026-09-28T10:00:00Z',
  handled_at: null,
  handled_by: null,
  handled_note: null,
}

const fromVisitor: Feedback = {
  ...fromAccount,
  id: 'f_2',
  kind: 'IDEA',
  status: 'HANDLED',
  message: 'Let me filter the marketplace by reward asset.',
  sender: null,
  email: 'visitor@example.com',
  path: null,
  viewport_width: null,
  viewport_height: null,
  handled_at: '2026-09-29T09:00:00Z',
  handled_by: { id: 'u_3', username: 'mod', display_name: 'Maintainer', avatar_url: null },
  handled_note: 'Shipped with the asset filter.',
}

const page: FeedbackPage = {
  items: [fromAccount, fromVisitor],
  total: 2,
  page: 1,
  page_size: 20,
  pages: 1,
  new_count: 1,
}

const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>()

const staff = makeMe({ role: 'MODERATOR', permissions: ['bounty:moderate', 'feedback:review'] })

function render() {
  return renderWithProviders(<AdminFeedbackPage />, { me: staff, route: '/admin/feedback' })
}

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockImplementation(async (url) => {
    if (url.includes('/handle')) return jsonResponse({ ...fromAccount, status: 'HANDLED' })
    if (url.includes('/admin/feedback')) return jsonResponse(page)
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('AdminFeedbackPage', () => {
  it('lists notes with who sent them and how many are waiting', async () => {
    render()
    const table = await screen.findByRole('table', { name: 'Feedback' })
    expect(within(table).getByText('Grace Hopper')).toBeInTheDocument()
    expect(within(table).getByText('Anonymous')).toBeInTheDocument()
    expect(within(table).getByRole('link', { name: 'visitor@example.com' })).toHaveAttribute(
      'href',
      'mailto:visitor@example.com',
    )
    expect(within(table).getByText('Waiting')).toBeInTheDocument()
    expect(within(table).getByText('Handled')).toBeInTheDocument()
    expect(screen.getByText('1 waiting')).toBeInTheDocument()
  })

  it('shows the captured context when a row is expanded', async () => {
    const user = userEvent.setup()
    render()
    const table = await screen.findByRole('table', { name: 'Feedback' })
    await user.click(within(table).getAllByRole('button', { name: /Show the full note/ })[0]!)

    expect(await screen.findByText('Chrome on macOS')).toBeInTheDocument()
    expect(screen.getAllByText('1,280 × 800').length).toBeGreaterThan(0)
  })

  it('asks the API to mark a note handled', async () => {
    const user = userEvent.setup()
    render()
    const table = await screen.findByRole('table', { name: 'Feedback' })
    await user.click(within(table).getByRole('button', { name: 'Mark handled' }))

    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText(/^Note/), 'Fixed in the escrow view.')
    await user.click(within(dialog).getByRole('button', { name: 'Mark handled' }))

    const call = fetchMock.mock.calls.find(([url]) => url.includes('/handle'))
    expect(call?.[0]).toContain('/admin/feedback/f_1/handle')
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      handled: true,
      note: 'Fixed in the escrow view.',
    })
  })

  it('filters by kind and status', async () => {
    const user = userEvent.setup()
    render()
    await screen.findByRole('table', { name: 'Feedback' })

    await user.click(screen.getByLabelText('Filter by type'))
    await user.click(await screen.findByRole('option', { name: 'Praise' }))

    const requested = fetchMock.mock.calls.map(([url]) => url).filter((u) => u.includes('/admin/feedback'))
    expect(requested.some((u) => u.includes('kind=PRAISE'))).toBe(true)
  })
})
