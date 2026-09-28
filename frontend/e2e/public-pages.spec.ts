import { expect, expectNoHorizontalOverflow, test } from './fixtures'
import { CONTRIBUTOR } from './support/accounts'

/** Journey 15: public marketing pages, profiles and the 404 page (all viewports). */

const narrow = (name: string) => name !== 'desktop-chromium'

test.describe('landing page', () => {
  test('hero, featured bounties, stats with methodology and the FAQ accordion', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('Work gets done')
    await expect(page.getByRole('main').getByRole('link', { name: 'Browse bounties' }).first()).toBeVisible()

    // The hero's reward pool shows real open bounties from the API as tokens, each linking to its detail page.
    const hero = page.locator('section[aria-labelledby="hero-title"]')
    const pool = hero.getByRole('group', { name: 'Open bounty rewards' })
    const token = pool.locator('[data-reward-token]').first()
    await expect(token).toBeVisible()
    await expect(token).toHaveAttribute('href', /^\/bounties\/[a-z0-9-]+$/)
    await expect(token).toContainText('XLM')
    await expect(token).toHaveAttribute('aria-label', /XLM reward, (funded in escrow|not funded yet)$/)

    // Below it, the open bounties rail: real cards, with previous / next controls.
    const rail = page.locator('section[aria-labelledby="open-bounties-title"]')
    await expect(rail.getByRole('heading', { name: 'Open bounties' })).toBeVisible()
    await expect(
      rail.getByRole('region', { name: 'Open bounties list' }).getByRole('article').first(),
    ).toBeVisible()
    await expect(rail.getByRole('button', { name: 'Next open bounties' })).toBeVisible()

    const stats = page.locator('section[aria-labelledby="stats-title"]')
    await stats.scrollIntoViewIfNeeded()
    await expect(stats.getByText('Verified payout volume')).toBeVisible()
    await expect(stats.getByText(/Network: Testnet/)).toBeVisible()
    await stats.getByRole('button', { name: 'How we count' }).click()
    const methodology = page.getByRole('dialog').filter({ hasText: /count|method/i })
    await expect(methodology).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(methodology).toBeHidden()

    const faq = page.locator('section#faq')
    await faq.scrollIntoViewIfNeeded()
    const first = faq.getByRole('button').first()
    await expect(first).toHaveAttribute('aria-expanded', 'false')
    await first.click()
    await expect(first).toHaveAttribute('aria-expanded', 'true')
    await expect(faq.getByRole('region').first()).toBeVisible()
    await first.click()
    await expect(first).toHaveAttribute('aria-expanded', 'false')
    await expectNoHorizontalOverflow(page, 'landing')
  })

  test('in-page anchor links scroll to their section', async ({ page }, testInfo) => {
    await page.goto('/about')
    if (narrow(testInfo.project.name)) {
      await page.getByRole('button', { name: 'Open menu' }).click()
      await page.getByRole('dialog', { name: 'Menu' }).getByRole('link', { name: 'Escrow contract' }).click()
    } else {
      await page.getByRole('contentinfo').getByRole('link', { name: 'Escrow contract' }).click()
    }
    await expect(page).toHaveURL(/\/#escrow$/)
    await expect(page.getByRole('heading', { name: /what happens to the money/i })).toBeInViewport({
      timeout: 10_000,
    })
  })
})

test.describe('content pages', () => {
  for (const [path, heading] of [
    ['/how-it-works', /verified payout/i],
    ['/about', /./],
    ['/guide', /./],
    ['/terms', /terms/i],
    ['/privacy', /privacy/i],
  ] as const) {
    test(`${path} renders with a single h1 and no overflow`, async ({ page }) => {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(heading)
      await expect(page.getByRole('contentinfo')).toBeVisible()
      await expectNoHorizontalOverflow(page, path)
    })
  }
})

test('guide: the contents highlight the section being read', async ({ page }, testInfo) => {
  test.skip(narrow(testInfo.project.name), 'the contents column is shown on desktop only')
  await page.goto('/guide')
  const contents = page.getByRole('navigation', { name: 'On this page' })
  const current = contents.locator('a[aria-current="location"]')
  await expect(current).toHaveText('Getting started')

  // Scrolling the reader to a section moves the highlight there.
  await page
    .locator('#payouts')
    .evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 120))
  await expect(current).toHaveText('Payouts')

  // Clicking an entry highlights it straight away; the end of the page highlights the last section.
  await contents.getByRole('link', { name: 'Fees' }).click()
  await expect(current).toHaveText('Fees')
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect(current).toHaveText('Glossary')
})

test('public profile shows identity, self-reported skills and stats', async ({ page }) => {
  await page.goto(`/u/${CONTRIBUTOR.username}`)
  await expect(page.getByRole('heading', { level: 1, name: CONTRIBUTOR.displayName })).toBeVisible()
  await expect(page.getByText(`@${CONTRIBUTOR.username}`).first()).toBeVisible()
  await expect(page.getByText('react', { exact: true }).first()).toBeVisible()
  await expectNoHorizontalOverflow(page, 'profile')
})

test('unknown public profile shows a not-found state', async ({ page }) => {
  await page.goto('/u/no-such-user-e2e')
  await expect(page.getByRole('heading', { name: /not found|page not found|no such/i }).first()).toBeVisible()
})

test('404 page offers a way back', async ({ page }) => {
  await page.goto('/definitely-not-a-page')
  await expect(page.getByRole('heading', { name: /page not found/i })).toBeVisible()
  await page
    .getByRole('main')
    .getByRole('link', { name: /home|back|marketplace|bounties/i })
    .first()
    .click()
  await expect(page).not.toHaveURL(/definitely-not-a-page/)
})

test('unknown bounty slug shows the not-found page', async ({ page }) => {
  await page.goto('/bounties/this-bounty-does-not-exist-e2e')
  await expect(page.getByRole('heading', { name: /page not found/i })).toBeVisible()
})
