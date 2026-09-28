import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { makeBounty } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'

import { BountyCard } from './BountyCard'
import { FundingStatusBadge } from './FundingStatusBadge'

describe('BountyCard', () => {
  it('renders title, reward per position, total, skills and link', async () => {
    renderWithProviders(<BountyCard bounty={makeBounty()} />, { me: null })

    const article = await screen.findByRole('article', { name: /soroban event indexer/i })
    const link = within(article).getByRole('link', { name: 'Add a Soroban event indexer' })
    expect(link).toHaveAttribute('href', '/bounties/add-soroban-indexer')
    expect(within(article).getByText('1,250.5')).toBeInTheDocument()
    expect(within(article).getByText(/2 positions, 2,501 XLM total/)).toBeInTheDocument()
    expect(within(article).getByRole('list', { name: 'Required skills' })).toHaveTextContent('rust')
    expect(within(article).getByText(/3 applicants/)).toBeInTheDocument()
    expect(within(article).getByText('2 of 2 open')).toBeInTheDocument()
    expect(within(article).getByText('Funded in escrow')).toBeInTheDocument()
  })

  it('never labels an unfunded or pending bounty as funded', async () => {
    renderWithProviders(<BountyCard bounty={makeBounty({ status: 'OPEN', funding_status: 'UNFUNDED' })} />, {
      me: null,
    })
    const article = await screen.findByRole('article')
    expect(within(article).getByText('Unfunded')).toBeInTheDocument()
    expect(within(article).queryByText(/funded in escrow/i)).not.toBeInTheDocument()
  })
})

describe('FundingStatusBadge', () => {
  const cases = [
    ['FUNDED', undefined, 'Funded in escrow', 'funded'],
    ['PARTIALLY_FUNDED', undefined, 'Partially funded', 'partial'],
    ['UNFUNDED', undefined, 'Unfunded', 'unfunded'],
    ['PENDING', undefined, 'Funding pending', 'pending'],
    ['SETTLED', 'COMPLETED', 'Paid out', 'completed'],
    ['UNFUNDED', 'CANCELLED', 'Cancelled before funding', 'cancelled'],
    ['FUNDED', 'DISPUTED', 'Disputed, escrow locked', 'disputed'],
    ['REFUNDED', 'CANCELLED', 'Refunded', 'refunded'],
  ] as const

  it.each(cases)('%s (bounty %s) → "%s"', async (status, bountyStatus, label, tone) => {
    renderWithProviders(<FundingStatusBadge status={status} bountyStatus={bountyStatus} />)
    const text = await screen.findByText(label)
    const badge = text.closest('[data-funding]')
    expect(badge).toHaveAttribute('data-funding', tone)
  })

  it('only uses the word "Funded" for FUNDED', async () => {
    for (const status of [
      'UNFUNDED',
      'PENDING',
      'PARTIALLY_FUNDED',
      'REFUND_PENDING',
      'REFUNDED',
      'SETTLED',
    ] as const) {
      const { unmount } = renderWithProviders(<FundingStatusBadge status={status} />)
      await screen.findByText(/Funding:/)
      expect(screen.queryByText(/^Funded/)).not.toBeInTheDocument()
      unmount()
    }
  })
})
