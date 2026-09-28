import type { Locator, Page } from '@playwright/test'

import { expect, test } from './fixtures'

/**
 * The animated paths, run with motion on (the `motion` project; every other project runs as a reduced-motion
 * user). Covers the smooth-scroll engines, the reward pool, the draggable rail, the pinned story and the
 * boneyard skeletons, plus the reduced-motion fallback.
 */

async function translateX(el: Locator): Promise<number> {
  return el.evaluate((node) => new DOMMatrix(getComputedStyle(node).transform).m41)
}

async function centerOf(el: Locator) {
  const box = (await el.boundingBox())!
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}

/** Waits until the reward tokens stop moving (the entrance has finished). */
async function waitForPoolToSettle(page: Page) {
  const tokens = page.locator('[data-reward-token]')
  await expect(tokens.first()).toBeVisible({ timeout: 15_000 })
  let last = ''
  await expect
    .poll(
      async () => {
        const now = JSON.stringify(
          await tokens.evaluateAll((els) => els.map((e) => e.getBoundingClientRect().y)),
        )
        const stable = now === last
        last = now
        return stable
      },
      { intervals: [400], timeout: 15_000 },
    )
    .toBe(true)
}

async function wheelUntil(page: Page, done: () => Promise<boolean>, step = 350, max = 40) {
  await page.mouse.move(640, 400)
  for (let i = 0; i < max && !(await done()); i++) {
    await page.mouse.wheel(0, step)
    await page.waitForTimeout(250)
  }
}

test('landing: ScrollSmoother, the reward pool, the pinned story and the escrow vault', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /work gets done/i })).toBeVisible()

  // ScrollSmoother is driving the page (the story content is transformed, not natively scrolled).
  await expect(page.locator('#smooth-wrapper')).toHaveCSS('position', 'fixed')

  // Tokens rise onto the floor and settle; dragging one moves it without opening the bounty.
  await waitForPoolToSettle(page)
  const token = page.locator('[data-reward-token]').first()
  const before = await centerOf(token)
  await page.mouse.move(before.x, before.y)
  await page.mouse.down()
  await page.mouse.move(before.x - 90, before.y - 140, { steps: 12 })
  await page.mouse.up()
  await expect(page).toHaveURL(/\/$/)
  await expect.poll(async () => Math.round((await centerOf(token)).x)).not.toBe(Math.round(before.x))

  // The pinned story advances as you scroll: the step counter moves past the first step.
  const counter = page.locator('#how-it-works p[aria-live="polite"]')
  await wheelUntil(page, async () => /^0[2-5]/.test((await counter.textContent().catch(() => '')) ?? ''))
  await expect(counter).toContainText(/0[2-5]/)
  await expect(page.locator('#how-it-works li[data-state="active"]')).toHaveCount(1)

  // Further down, the escrow vault draws the lifecycle and the ring marking the current state appears.
  const ring = page.locator('#escrow [data-current]')
  await wheelUntil(
    page,
    async () => (await ring.evaluate((el) => Number(getComputedStyle(el).opacity))) > 0.5,
    400,
  )
  await expect.poll(() => ring.evaluate((el) => Number(getComputedStyle(el).opacity))).toBeGreaterThan(0.5)
})

test('landing: the story hands off to the contributor track, and escrow states explain themselves on hover', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /work gets done/i })).toBeVisible()

  // Scrolling through the pinned story reaches the contributor's steps (green) after the handoff.
  const counter = page.locator('#how-it-works p[aria-live="polite"]')
  await wheelUntil(
    page,
    async () => /when you do the work/.test((await counter.textContent().catch(() => '')) ?? ''),
    400,
    60,
  )
  await expect(counter).toContainText('when you do the work')
  await expect(page.getByRole('button', { name: 'When you do the work' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )

  // The escrow diagram stays pinned while it draws; pointing at a state explains it.
  const funded = page.locator('#escrow [data-node="funded"] > g')
  await wheelUntil(
    page,
    async () =>
      (await page.locator('#escrow [data-current]').evaluate((el) => Number(getComputedStyle(el).opacity))) >
      0.5,
    400,
    30,
  )
  await funded.hover()
  await expect(page.locator('#escrow figcaption')).toContainText(
    'The full amount is confirmed in the contract',
  )
})

test('landing: hovering a reward coin shows its bounty', async ({ page }) => {
  await page.goto('/')
  await waitForPoolToSettle(page)
  const coin = page.locator('[data-reward-token]').first()
  const label = (await coin.getAttribute('aria-label'))!.split(':')[0]
  await coin.hover()
  await expect(coin.locator('span[aria-hidden]').filter({ hasText: label }).first()).toBeVisible()
})

test('theme switch animates between light and dark', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Switch to dark theme' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('button', { name: 'Switch to light theme' }).click()
  await expect(page.locator('html')).not.toHaveClass(/dark/)
})

test('landing: clicking a reward token opens its bounty', async ({ page }) => {
  await page.goto('/')
  await waitForPoolToSettle(page)
  const token = page.locator('[data-reward-token]').first()
  const href = await token.getAttribute('href')
  await token.click()
  await expect(page).toHaveURL(new RegExp(`${href}$`))
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
})

test('landing: the open bounties rail moves with the buttons and when dragged', async ({ page }) => {
  await page.goto('/')
  const rail = page.getByRole('region', { name: 'Open bounties list' })
  const track = rail.locator('ul').first()
  await expect(track.getByRole('article').first()).toBeAttached()
  // Move the native scroll position (ScrollSmoother follows it) so the rail sits just below the header.
  await rail.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 140))
  // ScrollSmoother eases into place; click only once the rail has stopped moving.
  let lastY = NaN
  await expect
    .poll(async () => {
      const y = Math.round((await rail.boundingBox())?.y ?? NaN)
      const still = y === lastY
      lastY = y
      return still
    })
    .toBe(true)

  const settledX = async () => {
    let last = NaN
    await expect
      .poll(async () => {
        const x = await translateX(track)
        const still = x === last
        last = x
        return still
      })
      .toBe(true)
    return last
  }

  const start = await settledX()
  const next = await centerOf(page.getByRole('button', { name: 'Next open bounties' }))
  await page.mouse.click(next.x, next.y)
  await expect.poll(() => translateX(track)).toBeLessThan(start - 50)
  const afterButton = await settledX()

  // Drag back to the right from the middle of the visible rail: it follows the pointer and no card opens.
  const middle = await centerOf(rail)
  await page.mouse.move(middle.x, middle.y)
  await page.mouse.down()
  await page.mouse.move(middle.x + 260, middle.y, { steps: 12 })
  await page.mouse.up()
  await expect(page).toHaveURL(/\/$/)
  await expect.poll(() => translateX(track)).toBeGreaterThan(afterButton + 50)
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

  test('no smooth scrolling, and content is visible without waiting for animations', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: /work gets done/i })).toBeVisible()
    await expect(page.locator('#smooth-wrapper')).not.toHaveCSS('position', 'fixed')
    await expect(page.locator('html')).not.toHaveClass(/lenis/)
    await expect(page.locator('[data-reward-token]').first()).toBeVisible()
    // Below-the-fold sections are rendered in place, not waiting to be revealed.
    await expect(page.locator('#escrow h3').first()).toHaveCSS('opacity', '1')
  })
})
