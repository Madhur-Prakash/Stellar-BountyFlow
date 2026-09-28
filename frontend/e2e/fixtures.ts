import { randomUUID } from 'node:crypto'

import {
  test as base,
  expect,
  type APIRequestContext,
  type BrowserContext,
  type Page,
} from '@playwright/test'

import type { SeededAccount } from './support/accounts'
import { resetRateLimits } from './support/redis'

/**
 * Shared E2E fixtures and helpers.
 *
 * Every test automatically fails on:
 * - uncaught page errors,
 * - `console.error` output from the app (browser network noise for expected
 *   4xx responses such as the anonymous `GET /auth/me` is ignored),
 * - any 5xx response from the API.
 * Tests that deliberately provoke an error can extend the allow-list with
 * `allowConsoleErrors(/pattern/)`.
 */

export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? 'http://localhost:8025'
export const API = '/api/v1'

/** Chrome logs every non-2xx fetch as a console error; those are asserted separately. */
const IGNORED_CONSOLE = [/Failed to load resource: the server responded with a status of 4\d\d/i]

type Guard = {
  errors: string[]
  allow: RegExp[]
  /** Starts watching another page (e.g. a second user's browser context). */
  watch: (page: Page, label?: string) => void
}

type Fixtures = {
  guard: Guard
  allowConsoleErrors: (...patterns: RegExp[]) => void
}

function makeGuard(): Guard {
  const guard: Guard = {
    errors: [],
    allow: [...IGNORED_CONSOLE],
    watch: (page, label = 'page') => {
      const allowed = (text: string) => guard.allow.some((re) => re.test(text))
      page.on('pageerror', (err) => {
        if (!allowed(err.message)) guard.errors.push(`[${label}] pageerror: ${err.message}`)
      })
      page.on('console', (msg) => {
        if (msg.type() !== 'error') return
        const text = msg.text()
        if (!allowed(text)) guard.errors.push(`[${label}] console.error: ${text}`)
      })
      page.on('response', (res) => {
        const url = new URL(res.url())
        if (res.status() >= 500 && url.pathname.startsWith('/api/')) {
          const text = `HTTP ${res.status()} ${res.request().method()} ${url.pathname}`
          if (!allowed(text)) guard.errors.push(`[${label}] ${text}`)
        }
      })
    },
  }
  return guard
}

export const test = base.extend<Fixtures>({
  guard: [
    async ({ page }, provide, testInfo) => {
      const guard = makeGuard()
      guard.watch(page)
      await provide(guard)
      if (guard.errors.length > 0) {
        const report = guard.errors.join('\n')
        await testInfo.attach('runtime-errors', { body: report, contentType: 'text/plain' })
        throw new Error(`Runtime errors during the test:\n${report}`)
      }
    },
    { auto: true },
  ],
  allowConsoleErrors: async ({ guard }, provide) => {
    await provide((...patterns: RegExp[]) => guard.allow.push(...patterns))
  },
})

export { expect }

// ---------------------------------------------------------------------------
// Identity helpers
// ---------------------------------------------------------------------------

export function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${randomUUID().slice(0, 6)}`
}

export type NewUser = { email: string; username: string; displayName: string; password: string }

export function newUser(prefix = 'e2e'): NewUser {
  const s = uniqueSuffix()
  return {
    email: `${prefix}-${s}@e2e.bountyflow.dev`,
    username: `${prefix}-${s}`.slice(0, 30),
    displayName: `E2E ${prefix} ${s.slice(-4)}`,
    password: `E2e-pass-${s}-Aa1!`,
  }
}

async function csrfHeader(context: BrowserContext): Promise<Record<string, string>> {
  const cookie = (await context.cookies()).find((c) => c.name === 'bf_csrf')
  return cookie ? { 'X-CSRF-Token': cookie.value } : {}
}

/** Authenticated JSON call through the page's cookie jar (setup shortcuts only). */
export async function apiCall<T = unknown>(
  page: Page,
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  path: string,
  data?: unknown,
): Promise<T> {
  const headers = method === 'GET' ? {} : await csrfHeader(page.context())
  const res = await page.request.fetch(`${API}${path}`, { method, data, headers })
  if (!res.ok()) throw new Error(`${method} ${path} → ${res.status()}: ${await res.text()}`)
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/**
 * Signs in through the normal /login form with email + password and waits
 * until the app has taken the user into the workspace (/app…).
 */
export async function signIn(page: Page, account: SeededAccount): Promise<void> {
  await resetRateLimits()
  await page.goto('/login')
  await page.getByLabel('Email').fill(account.email)
  await page.getByLabel('Password', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page, `sign in as ${account.email}`).toHaveURL((url) => /^\/app(\/|$)/.test(url.pathname))
}

/**
 * Signs in with email + password through the API, for sessions that only
 * make API calls (setup shortcuts; the cookies land in the page's context).
 */
export async function signInViaApi(page: Page, account: SeededAccount): Promise<void> {
  await resetRateLimits()
  const res = await page.request.post(`${API}/auth/login`, {
    data: { email: account.email, password: account.password },
  })
  if (!res.ok()) throw new Error(`login ${account.email} → ${res.status()}: ${await res.text()}`)
}

export async function logoutViaApi(page: Page): Promise<void> {
  await page.request.post(`${API}/auth/logout`, { headers: await csrfHeader(page.context()) })
  await page.context().clearCookies()
}

/** Registers a brand-new account through the API (setup shortcut). */
export async function registerViaApi(page: Page, user: NewUser = newUser()): Promise<NewUser> {
  await resetRateLimits()
  const res = await page.request.post(`${API}/auth/register`, {
    data: {
      email: user.email,
      password: user.password,
      username: user.username,
      display_name: user.displayName,
    },
  })
  expect(res.status(), `register ${user.email}: ${await res.text()}`).toBe(201)
  return user
}

// ---------------------------------------------------------------------------
// Mailpit
// ---------------------------------------------------------------------------

type MailpitSummary = { ID: string; Subject: string; Created: string }

async function mailpitSearch(request: APIRequestContext, to: string): Promise<MailpitSummary[]> {
  const res = await request.get(`${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`)
  if (!res.ok()) return []
  const body = (await res.json()) as { messages?: MailpitSummary[] }
  return body.messages ?? []
}

/**
 * Waits for an email to `to` whose subject matches, and returns the first
 * frontend link in it that carries a `token=` parameter.
 */
export async function readEmailLink(
  request: APIRequestContext,
  to: string,
  subject: RegExp,
  pathPart: string,
): Promise<{ url: string; token: string }> {
  let found: { url: string; token: string } | null = null
  await expect
    .poll(
      async () => {
        const messages = (await mailpitSearch(request, to)).filter((m) => subject.test(m.Subject))
        for (const m of messages) {
          const res = await request.get(`${MAILPIT_URL}/api/v1/message/${m.ID}`)
          if (!res.ok()) continue
          const msg = (await res.json()) as { Text?: string; HTML?: string }
          const haystack = `${msg.Text ?? ''}\n${msg.HTML ?? ''}`.replaceAll('&amp;', '&')
          const match = haystack.match(
            new RegExp(`https?://[^\\s"'<>]*${pathPart}\\?token=([A-Za-z0-9_\\-.~%]+)`),
          )
          if (match) {
            found = { url: match[0], token: decodeURIComponent(match[1]) }
            return true
          }
        }
        return false
      },
      // Generous: the worker delivers emails one at a time, and SMTP to Mailpit can take seconds each.
      { message: `email "${subject}" to ${to}`, timeout: 90_000, intervals: [500, 1000, 2000] },
    )
    .toBe(true)
  return found!
}

// ---------------------------------------------------------------------------
// Page helpers
// ---------------------------------------------------------------------------

/** No horizontal page overflow (1px tolerance for sub-pixel rounding). */
export async function expectNoHorizontalOverflow(page: Page, label = page.url()): Promise<void> {
  const { scrollWidth, innerWidth, offenders } = await page.evaluate(() => {
    const vw = window.innerWidth
    const out: string[] = []
    if (document.documentElement.scrollWidth > vw + 1) {
      for (const el of Array.from(document.body.querySelectorAll<HTMLElement>('*'))) {
        const r = el.getBoundingClientRect()
        if (r.width > 0 && r.right > vw + 1 && getComputedStyle(el).position !== 'fixed') {
          // Skip descendants of horizontally scrollable containers (they are contained).
          let p = el.parentElement
          let contained = false
          while (p && p !== document.body) {
            const s = getComputedStyle(p)
            if (
              (s.overflowX === 'auto' || s.overflowX === 'scroll' || s.overflowX === 'hidden') &&
              p.getBoundingClientRect().right <= vw + 1
            ) {
              contained = true
              break
            }
            p = p.parentElement
          }
          if (!contained)
            out.push(
              `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 80)} → right=${Math.round(r.right)}`,
            )
        }
        if (out.length >= 5) break
      }
    }
    return { scrollWidth: document.documentElement.scrollWidth, innerWidth: vw, offenders: out }
  })
  expect(scrollWidth, `horizontal overflow on ${label}: ${offenders.join(' | ')}`).toBeLessThanOrEqual(
    innerWidth + 1,
  )
}

/** Waits for the app shell/page to settle (no pending skeletons or route loaders). */
export async function waitForAppIdle(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded')
  // Lazy route chunks + data requests settle, then no loading placeholders (skeletons, boneyard bones, busy
  // regions such as the landing reward pool) remain.
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
  await expect(
    page
      .locator('main [data-slot="skeleton"], main [data-boneyard-overlay], main [aria-busy="true"]')
      .first(),
  ).toBeHidden({ timeout: 15_000 })
}

export async function toast(page: Page, text: string | RegExp) {
  await expect(page.locator('[data-sonner-toast]').filter({ hasText: text }).first()).toBeVisible()
}

export function isMobileProject(name: string): boolean {
  return name === 'mobile'
}
