import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, makeMe } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'

import { FeedbackLauncher } from './FeedbackLauncher'

const fetchMock = vi.fn<(input: string, init?: RequestInit) => Promise<Response>>()

function lastFeedbackBody(): Record<string, unknown> {
  const call = fetchMock.mock.calls.findLast(([url]) => url.includes('/feedback'))
  return JSON.parse(String(call?.[1]?.body ?? '{}')) as Record<string, unknown>
}

// The dialog is a lazy chunk fetched on the first click. Importing it once here means no individual test
// pays the module-load cost inside findBy's one-second budget, which is what made this file fail on CI.
beforeAll(async () => {
  await import('./FeedbackDialog')
}, 30_000)

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockImplementation(async (url) => {
    if (url.includes('/feedback')) return jsonResponse({ id: 'f_1' }, { status: 201 })
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

async function open(opts: Parameters<typeof renderWithProviders>[1] = {}) {
  const user = userEvent.setup()
  renderWithProviders(<FeedbackLauncher />, { me: null, ...opts })
  const button = screen.getByRole('button', { name: 'Feedback' })
  await user.click(button)
  // Suspense still has to resolve after the click, and CI machines are slower than this default allows.
  const dialog = await screen.findByRole('dialog', undefined, { timeout: 5_000 })
  return { user, button, dialog }
}

describe('FeedbackLauncher', () => {
  it('opens the dialog from the floating button and closes it back onto the button', async () => {
    const { user, button, dialog } = await open()
    expect(within(dialog).getByRole('heading', { name: 'Send feedback' })).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-expanded', 'true')

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    // Radix restores focus to the trigger after it has removed the content, not in the same tick.
    await waitFor(() => expect(button).toHaveFocus())
  })

  it('says what it captures and sends the path and viewport with the note', async () => {
    const { user, dialog } = await open({ route: '/bounties/fix-the-widget' })
    expect(within(dialog).getByText(/the page you are on/i)).toHaveTextContent('/bounties/fix-the-widget')

    await user.click(within(dialog).getByRole('radio', { name: 'Idea' }))
    await user.type(
      within(dialog).getByLabelText('Message'),
      'The funding progress bar stays at zero after the escrow confirms.',
    )
    await user.click(within(dialog).getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Thanks — this reached the maintainer')).toBeInTheDocument()
    expect(lastFeedbackBody()).toMatchObject({
      kind: 'IDEA',
      path: '/bounties/fix-the-widget',
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
    })
  })

  it('refuses a message under ten characters', async () => {
    const { user, dialog } = await open()
    await user.type(within(dialog).getByLabelText('Message'), 'too short')
    await user.click(within(dialog).getByRole('button', { name: 'Send' }))

    expect(await within(dialog).findByText('Write at least 10 characters.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => url.includes('/feedback'))).toBe(false)
  })

  it('offers an optional email when signed out and validates it', async () => {
    const { user, dialog } = await open()
    const email = within(dialog).getByLabelText(/^Email/)
    await user.type(within(dialog).getByLabelText('Message'), 'A note that is long enough to send.')
    await user.type(email, 'not-an-address')
    await user.click(within(dialog).getByRole('button', { name: 'Send' }))
    expect(await within(dialog).findByText('Enter a valid email address.')).toBeInTheDocument()

    await user.clear(email)
    await user.type(email, 'visitor@example.com')
    await user.click(within(dialog).getByRole('button', { name: 'Send' }))
    await screen.findByText('Thanks — this reached the maintainer')
    expect(lastFeedbackBody()).toMatchObject({ email: 'visitor@example.com' })
  })

  it('uses the account when signed in, and never sends an address beside it', async () => {
    const { user, dialog } = await open({ me: makeMe({ email: 'ada@example.com' }) })
    expect(within(dialog).getByText('Sent from your account, ada@example.com.')).toBeInTheDocument()
    expect(within(dialog).queryByLabelText(/^Email/)).not.toBeInTheDocument()

    await user.type(within(dialog).getByLabelText('Message'), 'Praise for the escrow timeline view.')
    await user.click(within(dialog).getByRole('button', { name: 'Send' }))
    await screen.findByText('Thanks — this reached the maintainer')
    expect(lastFeedbackBody().email).toBeNull()
  })

  it('shows the character count only as the message nears the limit', async () => {
    const { user, dialog } = await open()
    const message = within(dialog).getByLabelText('Message')
    await user.type(message, 'Short enough not to need a counter.')
    expect(within(dialog).queryByText(/\/2,000$/)).not.toBeInTheDocument()

    await user.clear(message)
    await user.paste('x'.repeat(1800))
    expect(await within(dialog).findByText('1,800/2,000')).toBeInTheDocument()
  })
})
