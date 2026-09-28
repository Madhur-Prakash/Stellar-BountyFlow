import type { Locator, Page } from '@playwright/test'

import { expect, expectNoHorizontalOverflow, signIn, test, waitForAppIdle } from './fixtures'
import { ADMIN, CONTRIBUTOR, REQUESTER, type SeededAccount } from './support/accounts'
import { ADMIN_ROUTES, APP_ROUTES, PUBLIC_ROUTES, requesterBountyId, seededIds, type RouteSpec } from './support/routes'

/**
 * Journey 16: responsive + accessibility audit across every route on all three
 * viewports (desktop 1280, tablet 768, mobile Pixel 7).
 */

async function auditRoute(page: Page, route: RouteSpec) {
  await page.goto(route.path)
  await waitForAppIdle(page)
  const main = page.locator('main')
  await expect(main, `${route.path}: one visible <main>`).toHaveCount(1)
  await expect(main).toBeVisible()
  await expect(page.getByRole('heading', { level: 1 }).first(), `${route.path}: has an h1`).toBeVisible()
  if (route.heading) await expect(page.getByRole('heading', { level: 1 }).first()).toHaveText(route.heading)
  await expect(page.getByText(/something went wrong|could not load/i), `${route.path}: no error state`).toHaveCount(0)
  await expectNoHorizontalOverflow(page, route.path)
}

async function auditAs(page: Page, account: SeededAccount | null, routes: RouteSpec[]) {
  if (account) await signIn(page, account)
  for (const route of routes) await auditRoute(page, route)
}

const isMobile = (name: string) => name === 'mobile'
const isDesktop = (name: string) => name === 'desktop-chromium'

test.describe('no horizontal overflow and sound page structure on every route', () => {
  test.describe.configure({ mode: 'parallel' })

  test('public pages', async ({ page }) => {
    test.setTimeout(150_000)
    const { publicBounty } = await seededIds(page)
    await auditAs(page, null, [...PUBLIC_ROUTES, { path: `/bounties/${publicBounty.slug}`, name: 'bounty-detail' }])
  })

  test('requester workspace', async ({ page }) => {
    test.setTimeout(150_000)
    await signIn(page, REQUESTER)
    const id = await requesterBountyId(page)
    await auditAs(page, null, [
      ...APP_ROUTES,
      { path: `/app/bounties/${id}`, name: 'manage' },
      { path: `/app/bounties/${id}/edit`, name: 'edit' },
      { path: `/app/bounties/${id}/applications`, name: 'applications' },
      { path: `/app/bounties/${id}/submissions`, name: 'submissions' },
    ])
  })

  test('contributor workspace', async ({ page }) => {
    test.setTimeout(120_000)
    await auditAs(page, CONTRIBUTOR, APP_ROUTES)
  })

  test('staff console', async ({ page }) => {
    test.setTimeout(120_000)
    await auditAs(page, ADMIN, ADMIN_ROUTES)
  })
})

test.describe('navigation', () => {
  test('marketing navigation: every target is reachable (mobile sheet on small screens)', async ({ page }, testInfo) => {
    await page.goto('/')
    const targets = ['Marketplace', 'How it works', 'Guide']
    if (isDesktop(testInfo.project.name)) {
      const nav = page.getByRole('navigation', { name: 'Primary' })
      for (const name of targets) await expect(nav.getByRole('link', { name })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Open menu' })).toBeHidden()
      return
    }
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeHidden()
    const expected: [string, RegExp][] = [
      ['Marketplace', /\/bounties$/],
      ['How it works', /\/how-it-works$/],
      ['Guide', /\/guide$/],
      ['About', /\/about$/],
    ]
    for (const [name, url] of expected) {
      await page.getByRole('button', { name: 'Open menu' }).click()
      const sheet = page.getByRole('dialog', { name: 'Menu' })
      await expect(sheet).toBeVisible()
      await expectInViewport(page, sheet)
      await sheet.getByRole('link', { name, exact: true }).click()
      await expect(page).toHaveURL(url)
      await expect(sheet).toBeHidden()
    }
    // Escape closes the sheet and returns focus to the trigger.
    await page.getByRole('button', { name: 'Open menu' }).click()
    await expect(page.getByRole('dialog', { name: 'Menu' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: 'Menu' })).toBeHidden()
    await expect(page.getByRole('button', { name: 'Open menu' })).toBeFocused()
  })

  test('workspace sidebar: collapses to a sheet on mobile and every item is reachable', async ({ page }, testInfo) => {
    await signIn(page, REQUESTER)
    await page.goto('/app')
    const items: [string, RegExp][] = [
      ['Dashboard', /\/app$/],
      ['My bounties', /\/app\/bounties$/],
      ['Applications', /\/app\/applications$/],
      ['Payments', /\/app\/payments$/],
      ['Transactions', /\/app\/transactions$/],
      ['Settings', /\/app\/settings$/],
    ]
    for (const [name, url] of items) {
      let scope: Locator = page.locator('[data-slot="sidebar-container"]')
      if (isMobile(testInfo.project.name)) {
        await page.getByRole('button', { name: 'Toggle navigation' }).click()
        scope = page.getByRole('dialog', { name: 'Workspace navigation' })
        await expect(scope).toBeVisible()
      }
      await scope.getByRole('link', { name, exact: true }).click()
      await expect(page).toHaveURL(url)
      if (isMobile(testInfo.project.name)) await expect(page.getByRole('dialog', { name: 'Workspace navigation' })).toBeHidden()
    }
  })
})

/** The element (once its enter animation has finished) lies fully inside the viewport. */
async function expectInViewport(page: Page, locator: Locator) {
  const vp = page.viewportSize()!
  await expect(async () => {
    const box = await locator.boundingBox()
    expect(box, 'element has a box').not.toBeNull()
    expect(box!.x).toBeGreaterThanOrEqual(-1)
    expect(box!.y).toBeGreaterThanOrEqual(-1)
    expect(box!.x + box!.width).toBeLessThanOrEqual(vp.width + 1)
    expect(box!.y + box!.height).toBeLessThanOrEqual(vp.height + 1)
  }).toPass({ timeout: 5_000 })
}

test('tables become cards below 1024px and scroll inside their container above', async ({ page }, testInfo) => {
  await signIn(page, ADMIN)
  for (const path of ['/admin/users', '/admin/transactions', '/admin/bounties']) {
    await page.goto(path)
    await waitForAppIdle(page)
    const main = page.getByRole('main')
    if (!isDesktop(testInfo.project.name)) {
      await expect(main.locator('table').first()).toBeHidden()
      await expect(main.getByRole('list').first()).toBeVisible()
    } else {
      const container = main.locator('[data-slot="table-container"]').first()
      await expect(container).toBeVisible()
      const { overflows, overflowX } = await container.evaluate((el) => ({
        overflows: el.scrollWidth > el.clientWidth + 1,
        overflowX: getComputedStyle(el).overflowX,
      }))
      if (overflows) expect(overflowX, `${path}: wide table scrolls in its container`).toMatch(/auto|scroll/)
    }
    await expectNoHorizontalOverflow(page, path)
  }
})

test('dialogs fit the viewport and trap focus', async ({ page }) => {
  await signIn(page, CONTRIBUTOR)
  const { publicBounty } = await seededIds(page)
  await page.goto(`/bounties/${publicBounty.slug}`)
  await page.getByRole('button', { name: /report/i }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expectInViewport(page, dialog)
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab')
    const inside = await dialog.evaluate((el) => el.contains(document.activeElement))
    expect(inside, 'focus stays inside the dialog').toBe(true)
  }
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('primary actions have touch targets of at least 40px', async ({ page }, testInfo) => {
  const check = async (locator: Locator, label: string) => {
    await expect(locator).toBeVisible()
    const box = (await locator.boundingBox())!
    expect(box.height, `${label} height`).toBeGreaterThanOrEqual(40)
    expect(box.width, `${label} width`).toBeGreaterThanOrEqual(40)
  }
  await page.goto('/')
  await check(page.getByRole('main').getByRole('link', { name: 'Browse bounties' }).first(), 'hero CTA')
  if (!isDesktop(testInfo.project.name)) await check(page.getByRole('button', { name: 'Open menu' }), 'menu button')

  await page.goto('/login')
  await check(page.getByRole('button', { name: 'Sign in', exact: true }), 'sign in')

  await page.goto('/bounties')
  await check(page.getByRole('searchbox', { name: /search bounties/i }), 'search')

  await signIn(page, REQUESTER)
  await page.goto('/app')
  await check(page.getByRole('main').getByRole('link', { name: /post a bounty/i }).first(), 'post a bounty')
  await check(page.getByRole('button', { name: 'Toggle navigation' }), 'sidebar toggle')
  await check(page.getByRole('button', { name: 'Account menu' }), 'account menu')
})

test('keyboard: skip link and main CTAs are reachable with a visible focus ring', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Skip to content' })
  await expect(skip).toBeFocused()
  await expect(skip).toBeVisible()

  const cta = page.getByRole('main').getByRole('link', { name: 'Browse bounties' }).first()
  let reached = false
  for (let i = 0; i < 40 && !reached; i++) {
    await page.keyboard.press('Tab')
    reached = await cta.evaluate((el) => el === document.activeElement)
  }
  expect(reached, 'Tab reaches the hero CTA').toBe(true)
  const ring = await cta.evaluate((el) => {
    const s = getComputedStyle(el)
    return { outline: s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0, shadow: s.boxShadow !== 'none' }
  })
  expect(ring.outline || ring.shadow, 'focused CTA shows a focus indicator').toBe(true)
})
