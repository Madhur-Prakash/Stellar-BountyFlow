import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderWithProviders } from '@/test/render'

import NotFoundPage from './NotFoundPage'

describe('NotFoundPage', () => {
  it('explains the 404 and offers ways back', async () => {
    renderWithProviders(<NotFoundPage />, { route: '/nope' })
    expect(await screen.findByRole('heading', { level: 1, name: /page not found/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to home/i })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: /explore bounties/i })).toHaveAttribute('href', '/bounties')
  })
})
