import { expect, test } from './fixtures'

/**
 * The motion that remains, run with motion on (the `motion` project; every other project runs as a
 * reduced-motion user): Lenis smooth scrolling on the public site, the escrow diagram explaining its states on
 * hover, the animated theme switch and the boneyard skeletons, plus the reduced-motion fallback.
 */

test('landing: Lenis scrolling, the live bounty preview and escrow states that explain themselves', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: /reward held in escrow/i })).toBeVisible()
  await expect(page.locator('html')).toHaveClass(/lenis/)

  // The hero previews a real open bounty and links to it.
  const preview = page.locator('section[aria-labelledby="hero-title"] article')
  await expect(preview).toBeVisible({ timeout: 15_000 })
  await expect(preview.locator('h2 a')).toHaveAttribute('href', /^\/bounties\/[a-z0-9-]+$/)

  // Pointing at a state in the escrow diagram explains it.
  const funded = page.locator('#escrow [data-node="funded"] > g')
  await funded.scrollIntoViewIfNeeded()
  await funded.hover()
  await expect(page.locator('#escrow figcaption')).toContainText('The full amount is confirmed in the contract')
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

  test('no smooth scrolling, and content is visible without waiting for animations', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: /reward held in escrow/i })).toBeVisible()
    await expect(page.locator('html')).not.toHaveClass(/lenis/)
    await expect(page.locator('section[aria-labelledby="hero-title"] article')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('#escrow h3').first()).toHaveCSS('opacity', '1')
  })
})
