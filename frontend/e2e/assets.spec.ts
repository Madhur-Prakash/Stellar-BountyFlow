import { apiCall, expect, signIn, test, uniqueSuffix } from './fixtures'
import { CONTRIBUTOR, REQUESTER } from './support/accounts'
import { signChainDialog } from './support/chain-ui'
import { acceptViaApi, applyViaApi, linkWalletViaApi, newSession } from './support/flows'
import { buyUsdc, hasUsdcTrustline, usdcBalance, USDC_IDENTIFIER } from './support/testnet-usdc'
import { installTestWallet } from './support/wallet'

/**
 * Reward assets on Stellar Testnet: a bounty paid in USDC, funded and paid out for real.
 *
 * Nothing about the money is faked. The requester's wallet starts with no USDC, so BountyFlow blocks funding
 * and offers the trustline; the trustline is added by signing a real `changeTrust`; the USDC itself is bought on
 * the Testnet order book (Circle's faucet needs a human, see support/testnet-usdc.ts); the escrow then holds
 * USDC through its Stellar Asset Contract and releases it to a contributor who has their own trustline.
 */

const REWARD = '5'

test('reward assets: a USDC bounty is blocked without a trustline, then funded and paid out in USDC', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(900_000)
  const wallet = await installTestWallet(page)
  await signIn(page, REQUESTER)
  await linkWalletViaApi(page, wallet)

  // --- The registry offers USDC beside XLM, and a bounty can be created in it. -----------------------
  await page.goto('/app/bounties/create')
  await page.getByLabel('Title').fill(`E2E USDC bounty ${uniqueSuffix()}`)
  await page
    .getByLabel('Summary')
    .fill('A bounty paid in USDC, created by the end-to-end suite to exercise reward assets.')
  await page
    .getByLabel('Full description')
    .fill(
      'This bounty is paid in Testnet USDC through the escrow contract, so the suite can verify trustlines.',
    )
  await page.getByLabel('Acceptance criteria').fill('The suite funds and pays it out in USDC.')
  const asset = page.getByLabel('Reward asset')
  await asset.click()
  await page.getByRole('option', { name: 'USDC', exact: false }).first().click()
  await expect(asset).toContainText('USDC')
  await page.getByLabel('Reward per position (USDC)').fill(REWARD)
  await expect(page.getByText(`${REWARD} USDC`).first()).toBeVisible()
  await page.getByRole('button', { name: 'Create bounty' }).click()
  await expect(page).toHaveURL(/\/app\/bounties\/[0-9a-f-]{36}/)
  const bountyId = new URL(page.url()).pathname.split('/')[3]!

  const detail = await apiCall<{ reward_asset: { code: string; identifier: string } }>(
    page,
    'GET',
    `/bounties/${bountyId}`,
  )
  expect(detail.reward_asset.code).toBe('USDC')
  expect(detail.reward_asset.identifier).toBe(USDC_IDENTIFIER)

  await page.getByRole('button', { name: 'Publish' }).click()
  await expect(page.getByText('Status: Open').first()).toBeVisible()

  // --- Without USDC the requester is stopped before signing, with what to do about it. ---------------
  const guidance = page.getByTestId('trustline-guidance')
  await expect(guidance).toBeVisible({ timeout: 30_000 })
  await expect(guidance).toContainText('Add a USDC trustline to fund this bounty')
  await expect(guidance).toContainText(
    'A trustline lets a Stellar account hold an asset other than XLM; adding one sets aside 0.5 XLM as a reserve.',
  )
  await expect(guidance.getByRole('link', { name: /Circle/i })).toHaveAttribute(
    'href',
    'https://faucet.circle.com',
  )
  expect(await hasUsdcTrustline(wallet.publicKey)).toBe(false)

  // --- The trustline is added through the UI, signed by the wallet, verified on-chain. ---------------
  await guidance.getByRole('button', { name: 'Add USDC trustline' }).click()
  await signChainDialog(page, /add usdc trustline/i)
  await expect
    .poll(() => hasUsdcTrustline(wallet.publicKey), {
      message: 'the trustline is visible on Horizon',
      timeout: 60_000,
    })
    .toBe(true)
  // With the trustline in place the notice becomes "not enough USDC", not "no trustline".
  await page.reload()
  await expect(guidance).toContainText('USDC available', { timeout: 30_000 })

  // --- Real Testnet USDC, bought on the order book, then the escrow is funded with it. ---------------
  await buyUsdc(wallet.keypair, { minimumUsdc: '30' })
  await page.reload()
  await expect(page.getByRole('button', { name: 'Fund escrow' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('trustline-guidance')).toHaveCount(0)

  await page.getByRole('button', { name: 'Fund escrow' }).click()
  const fundDialog = page.getByRole('dialog', { name: /fund escrow/i })
  await expect(fundDialog).toContainText(`${REWARD} USDC`)
  await signChainDialog(page, /fund escrow/i)
  await expect(page.getByText('Status: Funded').first()).toBeVisible({ timeout: 60_000 })
  const escrowCard = page.locator('[data-slot="card"]').filter({ hasText: 'In escrow' })
  await expect(escrowCard).toContainText('USDC')

  const funded = await apiCall<{ escrow: { asset: { identifier: string }; funded_amount: string } }>(
    page,
    'GET',
    `/bounties/${bountyId}`,
  )
  expect(funded.escrow.asset.identifier).toBe(USDC_IDENTIFIER)
  expect(Number(funded.escrow.funded_amount)).toBe(Number(REWARD))

  // --- A contributor without a trustline cannot be accepted; the message names them. -----------------
  const contributor = await newSession(browser, testInfo, guard, 'usdc-contributor')
  const contributorWallet = contributor.wallet!
  await signIn(contributor.page, CONTRIBUTOR)
  await linkWalletViaApi(contributor.page, contributorWallet)
  const application = await applyViaApi(contributor.page, bountyId)

  await page.goto(`/app/bounties/${bountyId}/applications`)
  const card = page.locator('li').filter({ hasText: CONTRIBUTOR.displayName }).first()
  await expect(card.getByText('No USDC trustline')).toBeVisible({ timeout: 30_000 })
  await card.getByRole('button', { name: 'Accept' }).click()
  const acceptDialog = page.getByRole('dialog', { name: /accept/i })
  await acceptDialog.getByRole('button', { name: 'Accept' }).click()
  await expect(card).toContainText(
    `${CONTRIBUTOR.displayName}'s wallet can't receive USDC yet. They need to add a USDC trustline.`.replace(
      "'",
      '’',
    ),
    { timeout: 20_000 },
  )

  // --- The contributor adds their own trustline from their profile, and is then accepted. ------------
  await contributor.page.goto('/app/profile#assets')
  const assets = contributor.page.locator('section#assets')
  await expect(assets.getByText('No USDC trustline')).toBeVisible({ timeout: 30_000 })
  await assets.getByRole('button', { name: 'Add USDC trustline' }).click()
  await signChainDialog(contributor.page, /add usdc trustline/i)
  await expect(assets.getByText('USDC trustline', { exact: true })).toBeVisible({ timeout: 30_000 })
  expect(await hasUsdcTrustline(contributorWallet.publicKey)).toBe(true)

  await acceptViaApi(page, application.id)
  await expect
    .poll(async () => (await apiCall<{ status: string }>(page, 'GET', `/bounties/${bountyId}`)).status, {
      timeout: 30_000,
    })
    .toBe('IN_PROGRESS')

  // --- Work is submitted, approved and paid out in USDC. ---------------------------------------------
  const submission = await apiCall<{ id: string }>(
    contributor.page,
    'POST',
    `/bounties/${bountyId}/submissions`,
    {
      description: 'The USDC reward flow is implemented and verified end to end by this suite.',
      evidence_url: 'https://github.com/bountyflow/e2e/pull/1',
    },
  )
  await apiCall(page, 'POST', `/submissions/${submission.id}/approve`, { feedback: 'Thanks' })

  const before = Number(await usdcBalance(contributorWallet.publicKey))
  await page.goto(`/app/bounties/${bountyId}/submissions`)
  await page.getByRole('button', { name: `Pay ${REWARD} USDC` }).click()
  await signChainDialog(page, /release reward|pay/i)

  await expect
    .poll(() => usdcBalance(contributorWallet.publicKey), {
      message: 'the contributor really received USDC',
      timeout: 120_000,
      intervals: [2000, 3000],
    })
    .toBe(String(before + Number(REWARD)))

  const settled = await apiCall<{ status: string; funding_status: string }>(
    page,
    'GET',
    `/bounties/${bountyId}`,
  )
  expect(settled.status).toBe('COMPLETED')
  expect(settled.funding_status).toBe('SETTLED')

  // Analytics keep the assets apart: USDC volume is never added to XLM.
  const stats = await apiCall<{
    verified_payout_volume: string
    payout_volume_by_asset: { asset: { code: string }; amount: string }[]
  }>(page, 'GET', '/analytics/public')
  const usdc = stats.payout_volume_by_asset.find((row) => row.asset.code === 'USDC')
  expect(Number(usdc?.amount ?? 0)).toBeGreaterThanOrEqual(Number(REWARD))
})
