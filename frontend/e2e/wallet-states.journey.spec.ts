import { apiCall, expect, signIn, test, uniqueSuffix } from './fixtures'
import { REQUESTER } from './support/accounts'
import { createBountyViaApi } from './support/flows'
import { installTestWallet } from './support/wallet'

/**
 * Wallet states on Stellar Testnet: what users see with no wallet chosen yet, and when the connected wallet has
 * not been verified for their account.
 */

test('with no wallet chosen the app offers the picker and funding starts there', async ({ page }) => {
  await signIn(page, REQUESTER)
  const bounty = await createBountyViaApi(page, { title: `E2E no-wallet bounty ${uniqueSuffix()}` })
  await apiCall(page, 'POST', `/bounties/${bounty.id}/publish`)

  await page.goto(`/app/bounties/${bounty.id}`)
  await expect(page.getByRole('banner').getByText('Testnet')).toBeVisible()
  const connect = page.getByRole('button', { name: 'Connect wallet' }).filter({ visible: true }).first()
  await expect(connect).toBeVisible({ timeout: 15_000 })

  // Funding without a wallet opens the picker instead of failing; wallets that are not installed link to them.
  await page.getByRole('button', { name: 'Fund escrow' }).click()
  const picker = page.getByRole('dialog', { name: 'Connect a wallet' })
  await expect(picker).toBeVisible({ timeout: 15_000 })
  await expect(picker.getByRole('link', { name: /install freighter/i })).toHaveAttribute(
    'href',
    'https://www.freighter.app/',
  )
})

test('a connected but unverified wallet is told to verify ownership before funding', async ({ page }) => {
  // A funded Testnet wallet that is connected in the browser but never verified for this account.
  await installTestWallet(page)
  await signIn(page, REQUESTER)
  const bounty = await createBountyViaApi(page, { title: `E2E unverified wallet bounty ${uniqueSuffix()}` })
  await apiCall(page, 'POST', `/bounties/${bounty.id}/publish`)

  await page.goto(`/app/bounties/${bounty.id}`)
  await expect(
    page.getByRole('button', { name: 'Wallet menu' }).filter({ visible: true }).first(),
  ).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Fund escrow' }).click()
  const dialog = page.getByRole('dialog', { name: /fund escrow/i })
  await expect(dialog.getByText(/not linked to your account/i)).toBeVisible({ timeout: 30_000 })
  const link = dialog.getByRole('link', { name: /connect and verify a wallet/i })
  await expect(link).toHaveAttribute('href', '/app/profile')
  await link.click()
  await expect(page).toHaveURL(/\/app\/profile$/)
  await expect(page.getByText('Linked wallets')).toBeVisible()
})
