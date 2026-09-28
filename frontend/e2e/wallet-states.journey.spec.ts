import { apiCall, expect, signIn, test, uniqueSuffix } from './fixtures'
import { REQUESTER } from './support/accounts'
import { createBountyViaApi } from './support/flows'
import { installTestWallet } from './support/wallet'

/**
 * Wallet states on Stellar Testnet: what users see without a wallet extension,
 * and when the connected wallet has not been verified for their account.
 */

test('without a wallet extension the app offers to install Freighter and funding explains why it cannot start', async ({
  page,
}) => {
  await signIn(page, REQUESTER)
  const bounty = await createBountyViaApi(page, { title: `E2E no-wallet bounty ${uniqueSuffix()}` })
  await apiCall(page, 'POST', `/bounties/${bounty.id}/publish`)

  await page.goto(`/app/bounties/${bounty.id}`)
  await expect(page.getByRole('banner').getByText('Testnet')).toBeVisible()
  const install = page.getByRole('link', { name: /install freighter/i }).filter({ visible: true }).first()
  await expect(install).toBeVisible({ timeout: 15_000 })
  await expect(install).toHaveAttribute('href', 'https://www.freighter.app/')

  await page.getByRole('button', { name: 'Fund escrow' }).click()
  const dialog = page.getByRole('dialog', { name: /fund escrow/i })
  await expect(dialog.getByText('Freighter is not installed. Install it to sign on-chain actions.')).toBeVisible({ timeout: 15_000 })
  await expect(dialog.getByRole('link', { name: 'Install Freighter' })).toHaveAttribute('href', 'https://www.freighter.app/')
})

test('a connected but unverified wallet is told to verify ownership before funding', async ({ page }) => {
  // A funded Testnet wallet that is connected in the browser but never verified for this account.
  await installTestWallet(page)
  await signIn(page, REQUESTER)
  const bounty = await createBountyViaApi(page, { title: `E2E unverified wallet bounty ${uniqueSuffix()}` })
  await apiCall(page, 'POST', `/bounties/${bounty.id}/publish`)

  await page.goto(`/app/bounties/${bounty.id}`)
  await expect(page.getByRole('button', { name: 'Wallet menu' }).filter({ visible: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Fund escrow' }).click()
  const dialog = page.getByRole('dialog', { name: /fund escrow/i })
  await expect(dialog.getByText(/not linked to your account/i)).toBeVisible({ timeout: 30_000 })
  const link = dialog.getByRole('link', { name: /connect and verify a wallet/i })
  await expect(link).toHaveAttribute('href', '/app/profile')
  await link.click()
  await expect(page).toHaveURL(/\/app\/profile$/)
  await expect(page.getByText('Linked wallets')).toBeVisible()
})
