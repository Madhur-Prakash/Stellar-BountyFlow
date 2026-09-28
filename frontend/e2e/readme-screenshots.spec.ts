import { apiCall, expect, signIn, test, waitForAppIdle } from './fixtures'
import { REQUESTER } from './support/accounts'
import { linkWalletViaApi } from './support/flows'
import { installTestWallet } from './support/wallet'

/**
 * Regenerates the README screenshots (docs/screenshots/*.png) in the default light theme. Run it against a freshly
 * seeded stack (see docs/testing.md), so the pictures show the seeded marketplace and nothing left over from tests:
 *   E2E_README_SHOTS=1 pnpm test:e2e readme-screenshots --project=desktop-chromium
 * The public pages are captured first; the workspace test then links a wallet to the seeded requester and prepares
 * (never signs) a funding transaction for one of her existing bounties. It creates no bounties.
 */
const OUT = '../docs/screenshots'

type Summary = { id: string; slug: string; status: string; funding_status: string; reward_amount: string }

const byReward = (a: Summary, b: Summary) => Number(b.reward_amount) - Number(a.reward_amount)

test.describe('README screenshots', () => {
  test.describe.configure({ mode: 'serial' })
  test.skip(!process.env.E2E_README_SHOTS, 'set E2E_README_SHOTS=1 to regenerate the README screenshots')
  test.beforeEach(async ({ page }, info) => {
    test.skip(info.project.name !== 'desktop-chromium', 'rendered once, from the desktop project')
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'light' })
  })

  test('public pages', async ({ page }) => {
    await page.goto('/')
    await waitForAppIdle(page)
    await expect(page.locator('[data-reward-token]').first()).toBeVisible()
    await page.screenshot({ path: `${OUT}/landing-desktop.png` })

    await page.goto('/bounties')
    await waitForAppIdle(page)
    await page.screenshot({ path: `${OUT}/marketplace-desktop.png` })

    // The detail page of a funded bounty if there is one, otherwise the highest reward on the marketplace.
    const list = await apiCall<{ items: Summary[] }>(page, 'GET', '/bounties?sort=reward_high&page_size=50')
    const bounty = list.items.find((b) => b.funding_status === 'FUNDED') ?? list.items[0]
    await page.goto(`/bounties/${bounty.slug}`)
    await waitForAppIdle(page)
    await page.screenshot({ path: `${OUT}/bounty-desktop.png` })

    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/bounties')
    await waitForAppIdle(page)
    await page.screenshot({ path: `${OUT}/marketplace-mobile.png` })
  })

  test('workspace and chain action', async ({ page }) => {
    test.setTimeout(180_000)
    // Shown as Freighter, the wallet real users sign with; signing still happens in the test process.
    const wallet = await installTestWallet(page, { name: 'Freighter' })
    await signIn(page, REQUESTER)
    await linkWalletViaApi(page, wallet)
    await page.goto('/app')
    await waitForAppIdle(page)
    await page.screenshot({ path: `${OUT}/dashboard-desktop.png` })

    // The review step of a real Testnet funding transaction for her largest open, unfunded bounty. It is never
    // signed; the prepared transaction expires unused.
    const mine = await apiCall<{ items: Summary[] }>(page, 'GET', '/bounties/mine?page_size=50')
    const bounty = mine.items
      .filter((b) => b.status === 'OPEN' && b.funding_status === 'UNFUNDED')
      .sort(byReward)[0]
    expect(bounty, 'the seeded requester has an open, unfunded bounty to fund').toBeTruthy()
    await page.goto(`/app/bounties/${bounty.id}`)
    await page.getByRole('button', { name: 'Fund escrow' }).click()
    const dialog = page.getByRole('dialog', { name: /fund escrow/i })
    await expect(dialog.getByRole('button', { name: /^Sign in / })).toBeEnabled({ timeout: 60_000 })
    await page.screenshot({ path: `${OUT}/chain-action-desktop.png` })
  })
})
