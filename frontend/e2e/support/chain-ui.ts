import type { Page } from '@playwright/test'

import { expect } from '../fixtures'

export const EXPLORER_TX = /^https:\/\/stellar\.expert\/explorer\/testnet\/tx\/[0-9a-f]{64}$/

/**
 * Completes an open ChainActionDialog: review → sign in the (test) wallet →
 * submit → wait for Stellar Testnet confirmation (up to 90 s) → Done.
 * Asserts the confirmed transaction links to the Testnet explorer.
 */
export async function signChainDialog(page: Page, name: RegExp): Promise<string> {
  const dialog = page.getByRole('dialog', { name })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('Testnet').first()).toBeVisible()
  const sign = dialog.getByRole('button', { name: /^Sign in / })
  await expect(sign).toBeEnabled({ timeout: 60_000 })
  await sign.click()
  await expect(dialog.getByText('Confirmed on Stellar')).toBeVisible({ timeout: 90_000 })
  const explorer = dialog.getByRole('link', { name: /view on explorer/i })
  await expect(explorer).toHaveAttribute('href', EXPLORER_TX)
  const href = (await explorer.getAttribute('href')) ?? ''
  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(dialog).toBeHidden()
  return href
}
