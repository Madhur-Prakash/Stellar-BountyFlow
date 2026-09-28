import type { Page } from '@playwright/test'

import { expect, logoutViaApi, signIn, test, waitForAppIdle } from './fixtures'
import { ADMIN, CONTRIBUTOR, REQUESTER } from './support/accounts'
import { ADMIN_ROUTES, APP_ROUTES, PUBLIC_ROUTES, requesterBountyId, seededIds, type RouteSpec } from './support/routes'

/**
 * Design review helper: full-page screenshots of every route at 375, 768 and
 * 1280 px, written to e2e/screenshots/ (git-ignored). Opt-in:
 *   E2E_SCREENSHOTS=1 pnpm test:e2e screenshots --project=desktop-chromium
 */
const WIDTHS = [375, 768, 1280]

test.describe('design screenshots', () => {
  test.skip(!process.env.E2E_SCREENSHOTS, 'set E2E_SCREENSHOTS=1 to capture design screenshots')
  test.beforeEach(async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop-chromium', 'the desktop project drives all widths')
    // Entrance animations finish instantly, so captures are deterministic.
    await page.emulateMedia({ reducedMotion: 'reduce' })
  })
  test.describe.configure({ mode: 'parallel' })
  test.setTimeout(600_000)

  async function shoot(page: Page, routes: RouteSpec[], prefix: string) {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width < 768 ? 812 : width < 1280 ? 1024 : 800 })
      for (const r of routes) {
        await page.goto(r.path)
        await waitForAppIdle(page)
        await expect(page.locator('main, [role="main"]').first()).toBeVisible()
        await page.screenshot({ path: `e2e/screenshots/${width}/${prefix}-${r.name}.png`, fullPage: true })
      }
    }
  }

  test('public pages', async ({ page }) => {
    const { publicBounty } = await seededIds(page)
    await shoot(page, [...PUBLIC_ROUTES, { path: `/bounties/${publicBounty.slug}`, name: 'bounty-detail' }], 'public')
  })

  test('requester workspace', async ({ page }) => {
    await signIn(page, REQUESTER)
    const id = await requesterBountyId(page)
    await shoot(
      page,
      [
        ...APP_ROUTES,
        { path: `/app/bounties/${id}`, name: 'manage-bounty' },
        { path: `/app/bounties/${id}/applications`, name: 'bounty-applications' },
        { path: `/app/bounties/${id}/submissions`, name: 'bounty-submissions' },
      ],
      'requester',
    )
    await logoutViaApi(page)
  })

  test('contributor workspace', async ({ page }) => {
    await signIn(page, CONTRIBUTOR)
    await shoot(page, APP_ROUTES.filter((r) => ['dashboard', 'applications', 'submissions', 'payments', 'transactions', 'notifications'].includes(r.name)), 'contributor')
  })

  test('admin console', async ({ page }) => {
    await signIn(page, ADMIN)
    await shoot(page, ADMIN_ROUTES, 'admin')
  })
})
