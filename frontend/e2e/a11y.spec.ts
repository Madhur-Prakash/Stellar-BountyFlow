import AxeBuilder from '@axe-core/playwright'
import type { Page, TestInfo } from '@playwright/test'

import { expect, signIn, test, waitForAppIdle } from './fixtures'
import { ADMIN, CONTRIBUTOR, REQUESTER, type SeededAccount } from './support/accounts'
import { requesterBountyId, seededIds } from './support/routes'

/**
 * Automated accessibility checks (axe-core, WCAG 2.1 A/AA) on key pages in
 * every viewport. Serious and critical violations fail the test.
 *
 * Pages are audited with reduced motion, i.e. in their settled state: entrance
 * animations fade content in from opacity 0, and auditing mid-animation would
 * report contrast failures for text that is still fading in (false positives).
 */
test.use({ reducedMotion: 'reduce' })

async function audit(page: Page, testInfo: TestInfo, label: string) {
  await waitForAppIdle(page)
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible()
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    // Toasts live outside the page flow and are announced via their own live region.
    .exclude('[data-sonner-toaster]')
    .analyze()
  const blocking = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  if (blocking.length) {
    await testInfo.attach(`axe-${label}`, { body: JSON.stringify(blocking, null, 2), contentType: 'application/json' })
  }
  const summary = blocking.map(
    (v) => `${v.id} (${v.impact}): ${v.help} → ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`,
  )
  expect(summary, `serious/critical axe violations on ${label}`).toEqual([])
}

const PUBLIC_PAGES = ['/', '/bounties', '/how-it-works', '/login', '/register', '/guide']

test.describe('axe: public pages', () => {
  for (const path of PUBLIC_PAGES) {
    test(`no serious violations on ${path}`, async ({ page }, testInfo) => {
      await page.goto(path)
      await audit(page, testInfo, path)
    })
  }

  test('no serious violations on a bounty detail page', async ({ page }, testInfo) => {
    const { publicBounty } = await seededIds(page)
    await page.goto(`/bounties/${publicBounty.slug}`)
    await audit(page, testInfo, 'bounty-detail')
  })
})

const SIGNED_IN: [string, SeededAccount, string[]][] = [
  ['requester', REQUESTER, ['/app', '/app/bounties', '/app/bounties/create', '/app/transactions', '/app/notifications']],
  ['contributor', CONTRIBUTOR, ['/app/applications', '/app/submissions', '/app/payments']],
  ['admin', ADMIN, ['/admin', '/admin/users', '/admin/disputes']],
]

test.describe('axe: signed-in pages', () => {
  for (const [role, account, paths] of SIGNED_IN) {
    test(`no serious violations for the ${role}`, async ({ page }, testInfo) => {
      test.setTimeout(120_000)
      await signIn(page, account)
      for (const path of paths) {
        await page.goto(path)
        await audit(page, testInfo, `${role}:${path}`)
      }
      if (account === REQUESTER) {
        await page.goto(`/app/bounties/${await requesterBountyId(page)}`)
        await audit(page, testInfo, 'manage-bounty')
      }
    })
  }
})

for (const path of ['/', '/bounties', '/login']) {
  test(`axe: dark theme contrast on ${path}`, async ({ page }, testInfo) => {
    await page.addInitScript(() => {
      try {
        localStorage.setItem('bf-ui-prefs', JSON.stringify({ state: { theme: 'dark' }, version: 0 }))
      } catch {
        /* storage unavailable */
      }
    })
    await page.goto(path)
    await expect(page.locator('html')).toHaveClass(/dark/)
    await audit(page, testInfo, `dark:${path}`)
  })
}
