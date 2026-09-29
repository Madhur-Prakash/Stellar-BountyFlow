import type { Page } from '@playwright/test'

import { apiCall, expect, newUser, registerViaApi, signIn, test, toast, uniqueSuffix } from './fixtures'
import { ADMIN } from './support/accounts'
import { installTestWallet } from './support/wallet'

/**
 * Privacy and data rights, end to end: a data export the worker builds and the browser downloads, an account
 * deletion request that can be cancelled, re-accepting an updated terms version, and an address the admin
 * screens being refused at wallet verification.
 *
 * The export and the screening list are built by the worker, so this spec needs the worker running alongside
 * the API (see docs/testing.md).
 */

type LegalVersion = { id: string; document: string; version: string; summary: string }
/** Signs in a brand-new account through the UI (registration + the normal login form). */
async function signInAsNewUser(page: Page) {
  const user = await registerViaApi(page, newUser('privacy'))
  await signIn(page, { ...user, username: user.username, displayName: user.displayName, role: 'USER' })
  return user
}

test('a user downloads a data export the worker built', async ({ page }) => {
  await signInAsNewUser(page)
  await page.goto('/app/privacy')
  await expect(page.getByRole('heading', { name: 'Privacy and data', level: 1 })).toBeVisible()

  await page.getByRole('button', { name: 'Request export' }).click()
  await toast(page, /export requested/i)

  // The worker's data-exports job runs every 10 seconds; the list polls until the archive is ready.
  const download = page.getByRole('button', { name: 'Download' })
  await expect(download).toBeVisible({ timeout: 90_000 })
  await expect(page.getByText('Ready')).toBeVisible()

  const started = page.waitForEvent('download')
  await download.click()
  const file = await started
  expect(file.suggestedFilename()).toMatch(/^bountyflow-data-.*\.json$/)

  // The archive is the user's own data, and it carries the sections the privacy notice promises.
  const stream = await file.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(chunk as Buffer)
  const archive = JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>
  expect(archive.export).toMatchObject({ format_version: 1 })
  expect(archive.profile).toBeTruthy()
  for (const section of ['wallets', 'bounties', 'transactions', 'notifications', 'audit_entries']) {
    expect(archive, `export section ${section}`).toHaveProperty(section)
  }
  // Screening decisions are deliberately not disclosed (docs/compliance.md).
  const entries = archive.audit_entries as { action: string }[]
  expect(entries.some((e) => e.action.startsWith('screening.'))).toBe(false)
})

test('a user schedules account deletion and cancels it', async ({ page }) => {
  const user = await signInAsNewUser(page)
  await page.goto('/app/privacy')

  await page.getByRole('button', { name: 'Delete account' }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete your account' })
  await expect(dialog).toBeVisible()

  // The password is checked before anything is scheduled.
  await dialog.getByLabel('Password').fill('not-the-right-password')
  await dialog.getByRole('button', { name: 'Schedule deletion' }).click()
  await expect(dialog.getByText('The password is not correct.')).toBeVisible()

  await dialog.getByLabel('Password').fill(user.password)
  await dialog.getByLabel(/why are you leaving/i).fill('End-to-end test.')
  await dialog.getByRole('button', { name: 'Schedule deletion' }).click()
  await expect(dialog).toBeHidden()
  await toast(page, /scheduled for deletion/i)

  await expect(page.getByText(/your account will be deleted on/i)).toBeVisible()
  // The account still works during the grace period.
  await page.goto('/app')
  await expect(page.getByRole('navigation', { name: 'Workspace navigation' })).toBeVisible()

  await page.goto('/app/privacy')
  await page.getByRole('button', { name: 'Cancel deletion' }).click()
  await toast(page, /deletion cancelled/i)
  await expect(page.getByRole('button', { name: 'Delete account' })).toBeVisible()
  const state = await apiCall<{ request: unknown }>(page, 'GET', '/privacy/deletion')
  expect(state.request).toBeNull()
})

test('a user re-accepts the terms after a new version takes effect', async ({ page, browser }) => {
  const user = await signInAsNewUser(page)
  await expect(page).toHaveURL(/\/app(\/|$)/)

  // An admin publishes a version that takes effect immediately.
  const staff = await browser.newContext()
  const staffPage = await staff.newPage()
  await signIn(staffPage, ADMIN)
  const version = await apiCall<LegalVersion>(staffPage, 'POST', '/admin/compliance/legal/versions', {
    document: 'TERMS',
    version: `e2e-${uniqueSuffix()}`,
    summary: 'End-to-end test version: clearer wording on disputes and refunds.',
  })
  expect(version.document).toBe('TERMS')

  // The workspace is held back until the user accepts it.
  await page.goto('/app')
  const gate = page.getByRole('heading', { name: 'We’ve updated our terms', level: 1 })
  await expect(gate).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(version.summary)).toBeVisible()
  await page.getByRole('button', { name: 'Accept and continue' }).click()

  await expect(gate).toBeHidden({ timeout: 20_000 })
  await expect(page.getByRole('navigation', { name: 'Workspace navigation' })).toBeVisible()

  // The acceptance is recorded against this account, so the gate does not come back.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'We’ve updated our terms' })).toBeHidden()
  const status = await apiCall<{ needs_acceptance: boolean }>(page, 'GET', '/legal/status')
  expect(status.needs_acceptance).toBe(false)
  expect(user.email).toBeTruthy()

  await staff.close()
})

test('an admin screens an address and verifying that wallet is refused', async ({ page, browser }) => {
  // A throwaway Testnet key that only this test uses; it is never funded and never signs anything on-chain.
  const wallet = await installTestWallet(page, { fund: false })

  const staff = await browser.newContext()
  const staffPage = await staff.newPage()
  await signIn(staffPage, ADMIN)
  await staffPage.goto('/admin/screening')
  await expect(staffPage.getByRole('heading', { name: 'Screening', level: 1 })).toBeVisible()

  await staffPage.getByRole('button', { name: 'Add address' }).click()
  const dialog = staffPage.getByRole('dialog', { name: 'Add a screened address' })
  await dialog.getByLabel('Stellar address').fill(wallet.publicKey)
  await dialog.getByLabel('Reason').fill(`End-to-end test entry ${uniqueSuffix()}`)
  await dialog.getByRole('button', { name: 'Add address' }).click()
  await expect(dialog).toBeHidden()
  await toast(staffPage, /address added/i)

  // The user proves ownership of that address; the signature is valid, and it is still refused.
  await signInAsNewUser(page)
  const challenge = await apiCall<{ challenge_xdr: string }>(page, 'POST', '/wallets/challenge', {
    public_address: wallet.publicKey,
  })
  const { TransactionBuilder, Networks } = await import('@stellar/stellar-sdk')
  const envelope = TransactionBuilder.fromXDR(challenge.challenge_xdr, Networks.TESTNET)
  envelope.sign(wallet.keypair)
  const refused = await page.request.fetch(`/api/v1/wallets/verify`, {
    method: 'POST',
    data: { public_address: wallet.publicKey, signed_challenge_xdr: envelope.toXDR() },
    headers: {
      'X-CSRF-Token': (await page.context().cookies()).find((c) => c.name === 'bf_csrf')?.value ?? '',
    },
  })
  expect(refused.status()).toBe(403)
  const body = (await refused.json()) as { error: { code: string; message: string } }
  expect(body.error.code).toBe('screening_blocked')
  // The message never says why; only staff see the reason.
  expect(body.error.message).not.toContain('End-to-end test entry')
  expect(await apiCall(page, 'GET', '/wallets')).toEqual([])

  // Staff see the blocked attempt, with its reason, in the decision log.
  await staffPage.reload()
  await expect(staffPage.getByText(wallet.publicKey.slice(0, 5)).first()).toBeVisible({ timeout: 20_000 })

  await staff.close()
})
