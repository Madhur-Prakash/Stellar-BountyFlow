import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { jsonResponse, makeMe } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'

import LoginPage from './LoginPage'
import RegisterPage from './RegisterPage'
import { passwordStrength, registerSchema } from './schemas'

const fetchMock = vi.fn<(input: string, init: RequestInit) => Promise<Response>>()

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('LoginPage', () => {
  it('validates required fields and email format without calling the API', async () => {
    const user = userEvent.setup()
    renderWithProviders(<LoginPage />, { route: '/login', path: '/login', me: null })

    await user.click(await screen.findByRole('button', { name: /^sign in$/i }))
    expect(await screen.findByText('Enter your email address.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Email'), 'not-an-email')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))
    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('submits credentials and redirects to ?next=', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValue(jsonResponse(makeMe()))
    const { router } = renderWithProviders(<LoginPage />, {
      route: '/login?next=%2Fapp%2Fsaved',
      path: '/login',
      me: null,
      routes: [{ path: '/app/saved', element: <p>saved page</p> }],
    })

    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))

    await waitFor(() => expect(router.state.location.pathname).toBe('/app/saved'))
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/v1/auth/login')
    expect(JSON.parse(String(init.body))).toEqual({
      email: 'ada@example.com',
      password: 'correct horse battery',
    })
  })

  it('shows the API error message on failure', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValue(
      jsonResponse(
        { error: { code: 'not_authenticated', message: 'Invalid email or password.' } },
        { status: 401 },
      ),
    )
    renderWithProviders(<LoginPage />, { route: '/login', path: '/login', me: null })
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: /^sign in$/i }))
    expect(await screen.findByText('Invalid email or password.')).toBeInTheDocument()
  })
})

describe('RegisterPage', () => {
  it('enforces username rules, password length, confirmation and terms', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RegisterPage />, { route: '/register', path: '/register', me: null })

    await user.type(await screen.findByLabelText('Email'), 'ada@example.com')
    await user.type(screen.getByLabelText('Username'), 'ab')
    await user.type(screen.getByLabelText('Display name'), 'Ada')
    await user.type(screen.getByLabelText('Password'), 'short')
    await user.type(screen.getByLabelText('Confirm password'), 'different')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByText('Usernames are 3–30 characters.')).toBeInTheDocument()
    expect(
      screen.getByText('Use at least 10 characters.', { selector: '[data-slot="form-message"]' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Passwords don’t match.')).toBeInTheDocument()
    expect(screen.getByText('You need to accept the terms to continue.')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('lowercases usernames and shows a strength meter', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RegisterPage />, { route: '/register', path: '/register', me: null })
    const username = await screen.findByLabelText('Username')
    await user.type(username, 'Ada_Dev')
    expect(username).toHaveValue('ada_dev')

    await user.type(screen.getByLabelText('Password'), 'Str0ng!Passphrase')
    expect(screen.getByText(/password strength:/i)).toHaveTextContent('Strong')
  })
})

describe('auth schemas', () => {
  const base = {
    email: 'a@b.co',
    username: 'good_name-1',
    display_name: 'A',
    password: 'abcdefghi1',
    confirm_password: 'abcdefghi1',
    accept_terms: true,
  }

  it('accepts valid usernames and rejects invalid characters', () => {
    expect(registerSchema.safeParse(base).success).toBe(true)
    expect(registerSchema.safeParse({ ...base, username: 'Bad Name' }).success).toBe(false)
    expect(registerSchema.safeParse({ ...base, username: 'x'.repeat(31) }).success).toBe(false)
    expect(
      registerSchema.safeParse({ ...base, password: 'a'.repeat(129), confirm_password: 'a'.repeat(129) })
        .success,
    ).toBe(false)
  })

  it('mirrors the API password rules (two character classes, no edge spaces)', () => {
    expect(
      registerSchema.safeParse({ ...base, password: 'abcdefghij', confirm_password: 'abcdefghij' }).success,
    ).toBe(false)
    expect(
      registerSchema.safeParse({ ...base, password: ' abcdefgh1', confirm_password: ' abcdefgh1' }).success,
    ).toBe(false)
    expect(
      registerSchema.safeParse({ ...base, password: 'correct horse', confirm_password: 'correct horse' })
        .success,
    ).toBe(true)
  })

  it('scores password strength', () => {
    expect(passwordStrength('').score).toBe(0)
    expect(passwordStrength('abc').score).toBeLessThanOrEqual(1)
    expect(passwordStrength('aaaaaaaaaaaa').score).toBeLessThanOrEqual(1)
    expect(passwordStrength('Str0ng!Passphrase').score).toBe(4)
  })
})
