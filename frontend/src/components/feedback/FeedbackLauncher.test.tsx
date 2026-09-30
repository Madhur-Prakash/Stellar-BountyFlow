import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, makeMe } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'
import { useUiPrefs } from '@/stores/ui-prefs'

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
  // The position is persisted, so each test starts from the default corner.
  useUiPrefs.getState().resetFeedbackPos()
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

/** Drags the button by dispatching the pointer sequence jsdom does not synthesise from userEvent. */
function dragBy(button: HTMLElement, dx: number, dy: number) {
  const box = button.getBoundingClientRect()
  const from = { clientX: box.left + 10, clientY: box.top + 10 }
  const opts = { bubbles: true, pointerId: 1, pointerType: 'mouse', button: 0 }
  button.dispatchEvent(new PointerEvent('pointerdown', { ...opts, ...from }))
  button.dispatchEvent(
    new PointerEvent('pointermove', { ...opts, clientX: from.clientX + dx, clientY: from.clientY + dy }),
  )
  button.dispatchEvent(
    new PointerEvent('pointerup', { ...opts, clientX: from.clientX + dx, clientY: from.clientY + dy }),
  )
}

describe('FeedbackLauncher', () => {
  it('stays where it is dragged, and remembers it', async () => {
    const user = userEvent.setup()
    renderWithProviders(<FeedbackLauncher />, { me: null })
    const button = screen.getByRole('button', { name: 'Feedback' })

    // Before it is moved it hangs off the bottom-right corner rather than a fixed coordinate.
    expect(button.style.left).toBe('')
    expect(button.style.right).not.toBe('')

    await act(async () => dragBy(button, -300, -200))
    await waitFor(() => expect(button.style.left).not.toBe(''))
    expect(button.style.top).not.toBe('')
    expect(button.style.right).toBe('')
    expect(useUiPrefs.getState().feedbackPos).not.toBeNull()

    // The drag must not be read as a request to open the dialog.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    // And it still opens on a real click.
    await user.click(button)
    expect(await screen.findByRole('dialog', undefined, { timeout: 5_000 })).toBeInTheDocument()
  })

  it('can be moved and put back from the keyboard', async () => {
    const user = userEvent.setup()
    renderWithProviders(<FeedbackLauncher />, { me: null })
    const button = screen.getByRole('button', { name: 'Feedback' })
    button.focus()

    await user.keyboard('{Alt>}{ArrowLeft}{/Alt}')
    await waitFor(() => expect(useUiPrefs.getState().feedbackPos).not.toBeNull())

    await user.keyboard('{Alt>}0{/Alt}')
    await waitFor(() => expect(useUiPrefs.getState().feedbackPos).toBeNull())
    expect(button.style.left).toBe('')
  })

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
