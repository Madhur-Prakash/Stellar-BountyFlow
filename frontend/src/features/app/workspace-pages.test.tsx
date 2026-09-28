import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { qk } from '@/lib/api/queries/keys'
import type { BlockchainTransaction, Dashboard, Page } from '@/lib/api/types'
import { makeBounty, makeMe } from '@/test/fixtures'
import { createTestQueryClient, renderWithProviders } from '@/test/render'

import DashboardPage from './DashboardPage'
import TransactionsPage from './TransactionsPage'

function makeDashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    active_bounties: 3,
    pending_applications_to_review: 4,
    submissions_awaiting_review: 0,
    pending_payments: 0,
    my_pending_applications: 1,
    my_active_assignments: 0,
    revision_requests: 1,
    recent_completed: [],
    recent_activity: [],
    recommendations: [makeBounty()],
    ...overrides,
  }
}

describe('DashboardPage', () => {
  it('links each item that needs attention to the page that resolves it', async () => {
    const client = createTestQueryClient()
    client.setQueryData(qk.dashboard, makeDashboard())
    const me = makeMe({
      onboarding: {
        email_verified: true,
        role_selected: true,
        profile_completed: false,
        wallet_connected: false,
        first_action_taken: false,
        completed: false,
      },
    })
    renderWithProviders(<DashboardPage />, { client, me })

    const attention = await screen.findByRole('region', { name: 'Needs your attention' })
    expect(within(attention).getByRole('link', { name: /finish setting up your account/i })).toHaveAttribute(
      'href',
      '/app/onboarding',
    )
    expect(within(attention).getByText('2 of 5 steps done')).toBeInTheDocument()
    expect(within(attention).getByRole('link', { name: /4 applications to review/ })).toHaveAttribute(
      'href',
      '/app/bounties',
    )
    expect(within(attention).getByRole('link', { name: /1 revision request/ })).toHaveAttribute(
      'href',
      '/app/submissions',
    )
    // Zero counts are not listed.
    expect(within(attention).queryByText(/submissions to review/)).not.toBeInTheDocument()

    expect(screen.getByRole('link', { name: /active bounties/i })).toHaveAttribute('href', '/app/bounties')
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Welcome back, Ada')
  })

  it('lists recommended bounties with their reward and funding state', async () => {
    const client = createTestQueryClient()
    client.setQueryData(qk.dashboard, makeDashboard())
    renderWithProviders(<DashboardPage />, { client, me: makeMe() })

    const recommended = await screen.findByRole('region', { name: 'Recommended for you' })
    expect(within(recommended).getByRole('link', { name: 'Add a Soroban event indexer' })).toHaveAttribute(
      'href',
      '/bounties/add-soroban-indexer',
    )
    expect(within(recommended).getByText('1,250.5')).toBeInTheDocument()
    expect(within(recommended).getAllByText('Funded in escrow').length).toBeGreaterThan(0)
    expect(within(recommended).getByRole('link', { name: 'View marketplace' })).toHaveAttribute(
      'href',
      '/bounties',
    )
  })

  it('says so when nothing needs attention', async () => {
    const client = createTestQueryClient()
    client.setQueryData(
      qk.dashboard,
      makeDashboard({ pending_applications_to_review: 0, revision_requests: 0, recommendations: [] }),
    )
    renderWithProviders(<DashboardPage />, { client, me: makeMe() })

    const attention = await screen.findByRole('region', { name: 'Needs your attention' })
    expect(within(attention).getByText('You’re all caught up.')).toBeInTheDocument()
    expect(screen.getByText('No recommendations yet')).toBeInTheDocument()
  })
})

describe('TransactionsPage', () => {
  it('shows each transaction with its status, amount and explorer link', async () => {
    const tx: BlockchainTransaction = {
      id: 't_1',
      bounty_id: 'b_1',
      bounty_title: 'Add a Soroban event indexer',
      user: null,
      transaction_hash: 'a'.repeat(64),
      transaction_type: 'PAYOUT',
      network: 'testnet',
      amount: '2.5000000',
      asset: { code: 'XLM', issuer: null, type: 'native', contract_id: null },
      status: 'CONFIRMED',
      source_address: null,
      destination_address: null,
      ledger_sequence: 1,
      submitted_at: '2026-09-27T10:00:00Z',
      confirmed_at: '2026-09-27T10:00:05Z',
      failure_reason: null,
      explorer_url: null,
      created_at: '2026-09-27T10:00:00Z',
    }
    const page: Page<BlockchainTransaction> = { items: [tx], total: 1, page: 1, page_size: 20, pages: 1 }
    const client = createTestQueryClient()
    client.setQueryData(qk.transactions.mine({ page: 1, page_size: 20 }), page)
    renderWithProviders(<TransactionsPage />, { client, me: makeMe() })

    const table = await screen.findByRole('table', { name: 'My transactions' })
    const row = within(table).getByRole('row', { name: /payout/i })
    expect(within(row).getByText('2.5')).toBeInTheDocument()
    expect(within(row).getByText('Confirmed')).toBeInTheDocument()
    expect(within(row).getByRole('link', { name: /view on explorer/i })).toHaveAttribute(
      'href',
      `https://stellar.expert/explorer/testnet/tx/${'a'.repeat(64)}`,
    )
    // The same records are available as a stacked list for small screens.
    expect(screen.getByRole('list', { name: 'My transactions' })).toBeInTheDocument()
  })
})
