import { screen } from '@testing-library/react'
import { useLocation } from 'react-router'
import { describe, expect, it } from 'vitest'

import { makeMe } from '@/test/fixtures'
import { renderWithProviders } from '@/test/render'

import { RedirectIfAuthed, RequireAuth, RequirePermission } from './guards'

function WhereAmI() {
  const loc = useLocation()
  return <p data-testid="location">{`${loc.pathname}${loc.search}`}</p>
}

const targets = [
  { path: '/login', element: <WhereAmI /> },
  { path: '/app', element: <WhereAmI /> },
  { path: '/app/onboarding', element: <WhereAmI /> },
  { path: '/app/applications', element: <WhereAmI /> },
]

describe('RequireAuth', () => {
  it('redirects anonymous users to /login with a return URL', async () => {
    renderWithProviders(
      <RequireAuth>
        <p>secret</p>
      </RequireAuth>,
      { route: '/app/payments?direction=sent', path: '/app/payments', me: null, routes: targets },
    )
    expect(await screen.findByTestId('location')).toHaveTextContent(
      `/login?next=${encodeURIComponent('/app/payments?direction=sent')}`,
    )
    expect(screen.queryByText('secret')).not.toBeInTheDocument()
  })

  it('renders children for signed-in users', async () => {
    renderWithProviders(
      <RequireAuth>
        <p>secret</p>
      </RequireAuth>,
      { route: '/app/payments', path: '/app/payments', me: makeMe(), routes: targets },
    )
    expect(await screen.findByText('secret')).toBeInTheDocument()
  })
})

describe('RequirePermission', () => {
  it('blocks users without the permission', async () => {
    renderWithProviders(
      <RequirePermission permission="bounty:moderate">
        <p>admin area</p>
      </RequirePermission>,
      { route: '/admin', path: '/admin', me: makeMe({ permissions: ['bounty:create'] }) },
    )
    expect(await screen.findByText(/don[’']t have access/i)).toBeInTheDocument()
    expect(screen.queryByText('admin area')).not.toBeInTheDocument()
  })

  it('gates by permission, not role name', async () => {
    renderWithProviders(
      <RequirePermission permission="bounty:moderate">
        <p>admin area</p>
      </RequirePermission>,
      { route: '/admin', path: '/admin', me: makeMe({ role: 'USER', permissions: ['bounty:moderate'] }) },
    )
    expect(await screen.findByText('admin area')).toBeInTheDocument()
  })
})

describe('RedirectIfAuthed', () => {
  it('sends signed-in users to a safe ?next= target', async () => {
    renderWithProviders(
      <RedirectIfAuthed>
        <p>login form</p>
      </RedirectIfAuthed>,
      { route: '/login?next=%2Fapp%2Fapplications', path: '/login', me: makeMe(), routes: targets.slice(1) },
    )
    expect(await screen.findByTestId('location')).toHaveTextContent('/app/applications')
  })

  it('ignores open-redirect attempts and sends unfinished onboarding to /app/onboarding', async () => {
    const me = makeMe({ onboarding: { ...makeMe().onboarding, completed: false } })
    renderWithProviders(
      <RedirectIfAuthed>
        <p>login form</p>
      </RedirectIfAuthed>,
      { route: '/login?next=https%3A%2F%2Fevil.test', path: '/login', me, routes: targets.slice(1) },
    )
    expect(await screen.findByTestId('location')).toHaveTextContent('/app/onboarding')
  })

  it('shows the page to anonymous visitors', async () => {
    renderWithProviders(
      <RedirectIfAuthed>
        <p>login form</p>
      </RedirectIfAuthed>,
      { route: '/login', path: '/login', me: null },
    )
    expect(await screen.findByText('login form')).toBeInTheDocument()
  })
})
