import type { Page } from '@playwright/test'

import { expect, test } from './fixtures'

/**
 * The animated paths, run with motion on (the `motion` project; every other project runs as a reduced-motion
 * user): Lenis smooth scrolling, the hero's rotating bounty preview, the two scroll stories ("How a bounty moves"
 * and the escrow diagram), the animated theme switch and the boneyard skeletons, plus the reduced-motion fallback.
 */

async function wheelUntil(page: Page, done: () => Promise<boolean>, step = 350, max = 60) {
  await page.mouse.move(640, 400)
  for (let i = 0; i < max && !(await done()); i++) {
    await page.mouse.wheel(0, step)
    await page.waitForTimeout(220)
  }
}

test('landing: Lenis scrolling and the rotating bounty preview', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /reward held in escrow/i })).toBeVisible()
  await expect(page.locator('html')).toHaveClass(/lenis/)

  // The hero previews a real open bounty and links to it; with several open, it cycles through them.
  const preview = page.locator('section[aria-labelledby="hero-title"] article')
  await expect(preview).toBeVisible({ timeout: 15_000 })
  await expect(preview.locator('h2 a')).toHaveAttribute('href', /^\/bounties\/[a-z0-9-]+$/)
  const picker = page.getByRole('group', { name: 'Open bounties' })
  if (await picker.isVisible()) {
    const second = picker.getByRole('button').nth(1)
    await second.click()
    await expect(second).toHaveAttribute('aria-pressed', 'true')
  }
})

test('landing: "How a bounty moves" plays with the scroll and hands off to the contributor', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  const counter = page.locator('#how-it-works p[aria-live="polite"]')
  await counter.scrollIntoViewIfNeeded()

  await wheelUntil(page, async () => /^0[2-5]/.test((await counter.textContent()) ?? ''))
  await expect(counter).toContainText(/0[2-5]/)
  await expect(page.locator('#how-it-works li[data-state="active"]')).toHaveCount(1)

  await wheelUntil(page, async () => /when you do the work/.test((await counter.textContent()) ?? ''), 400)
  await expect(counter).toContainText('when you do the work')
  await expect(page.getByRole('button', { name: 'When you do the work' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
})

test('landing: the escrow diagram draws as you scroll, and its states explain themselves', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.locator('#escrow').scrollIntoViewIfNeeded()
  const ring = page.locator('#escrow [data-current]')
  await wheelUntil(
    page,
    async () => (await ring.evaluate((el) => Number(getComputedStyle(el).opacity))) > 0.5,
    400,
  )
  await expect.poll(() => ring.evaluate((el) => Number(getComputedStyle(el).opacity))).toBeGreaterThan(0.5)

  const funded = page.locator('#escrow [data-node="funded"] > g')
  await funded.hover()
  await expect(page.locator('#escrow figcaption')).toContainText(
    'The full amount is confirmed in the contract',
  )
})

test('landing: the hero preview opens its bounty', async ({ page }) => {
  await page.goto('/')
  const link = page.locator('section[aria-labelledby="hero-title"] article h2 a')
  await expect(link).toBeVisible({ timeout: 15_000 })
  const href = await link.getAttribute('href')
  await link.click()
  await expect(page).toHaveURL(new RegExp(`${href}$`))
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('theme switch animates between light and dark', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Switch to dark theme' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Switch to light theme' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
})

test('marketplace: Lenis smooth scrolling and captured skeletons while results load', async ({ page }) => {
  // Hold the results request so the loading state is visible.
  await page.route(/\/api\/v1\/bounties\?/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 2500))
    await route.continue()
  })
  await page.goto('/bounties')
  await expect(page.locator('[data-boneyard-overlay]').first()).toBeVisible()
  await expect(page.locator('html')).toHaveClass(/lenis/)
  await expect(page.getByRole('article').first()).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('[data-boneyard-overlay]')).toHaveCount(0)
})

test.describe('reduced motion', () => {
  test.use({ reducedMotion: 'reduce' })

  test('no smooth scrolling or scroll stories, and content is visible at once', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: /reward held in escrow/i })).toBeVisible()
    await expect(page.locator('html')).not.toHaveClass(/lenis/)
    await expect(page.locator('section[aria-labelledby="hero-title"] article')).toBeVisible({
      timeout: 15_000,
    })
    // The stories render as static lists and a static diagram.
    await expect(page.locator('[data-how-story], [data-escrow-story]')).toHaveCount(0)
    await expect(page.locator('#escrow h3').first()).toHaveCSS('opacity', '1')
  })
})
