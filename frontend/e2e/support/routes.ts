import type { Page } from '@playwright/test'

import { API, apiCall } from '../fixtures'
import { CONTRIBUTOR } from './accounts'

export type RouteSpec = {
  path: string
  name: string
  /** Visible heading (level 1) expected on the page. */
  heading?: RegExp
}

type BountyLite = { id: string; slug: string; title: string; status: string; requester: { username: string } }

/** Resolves ids/slugs of seeded data needed by parameterised routes. */
export async function seededIds(page: Page) {
  const res = await page.request.get(`${API}/bounties?page_size=50`)
  const list = ((await res.json()) as { items: BountyLite[] }).items
  const publicBounty = list.find((b) => b.status === 'FUNDED') ?? list[0]
  return { publicBounty }
}

export async function requesterBountyId(page: Page): Promise<string> {
  const mine = await apiCall<{ items: BountyLite[] }>(
    page,
    'GET',
    '/bounties/mine?role=requester&page_size=50',
  )
  const b = mine.items.find((x) => x.status === 'IN_PROGRESS') ?? mine.items[0]
  return b.id
}

export const PUBLIC_ROUTES: RouteSpec[] = [
  { path: '/', name: 'landing', heading: /reward held in escrow/i },
  { path: '/bounties', name: 'marketplace', heading: /bounty marketplace/i },
  { path: '/how-it-works', name: 'how-it-works' },
  { path: '/about', name: 'about' },
  { path: '/guide', name: 'guide' },
  { path: '/terms', name: 'terms' },
  { path: '/privacy', name: 'privacy' },
  { path: `/u/${CONTRIBUTOR.username}`, name: 'public-profile' },
  { path: '/login', name: 'login', heading: /sign in/i },
  { path: '/register', name: 'register', heading: /create your account/i },
  { path: '/forgot-password', name: 'forgot-password' },
  { path: '/reset-password?token=invalid-token', name: 'reset-password' },
  { path: '/definitely-not-a-page', name: 'not-found', heading: /page not found/i },
]

export const APP_ROUTES: RouteSpec[] = [
  { path: '/app', name: 'dashboard' },
  { path: '/app/onboarding', name: 'onboarding' },
  { path: '/app/analytics', name: 'analytics' },
  { path: '/app/notifications', name: 'notifications' },
  { path: '/app/bounties', name: 'my-bounties' },
  { path: '/app/bounties/create', name: 'create-bounty' },
  { path: '/app/applications', name: 'applications' },
  { path: '/app/submissions', name: 'submissions' },
  { path: '/app/saved', name: 'saved' },
  { path: '/app/payments', name: 'payments' },
  { path: '/app/transactions', name: 'transactions' },
  { path: '/app/profile', name: 'profile' },
  { path: '/app/settings', name: 'settings' },
]

export const ADMIN_ROUTES: RouteSpec[] = [
  { path: '/admin', name: 'admin-overview' },
  { path: '/admin/users', name: 'admin-users' },
  { path: '/admin/bounties', name: 'admin-bounties' },
  { path: '/admin/reports', name: 'admin-reports' },
  { path: '/admin/disputes', name: 'admin-disputes' },
  { path: '/admin/transactions', name: 'admin-transactions' },
  { path: '/admin/audit-logs', name: 'admin-audit-logs' },
]
