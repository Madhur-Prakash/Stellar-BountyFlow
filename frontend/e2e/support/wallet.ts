import { Keypair, Networks, TransactionBuilder } from '@stellar/stellar-sdk'
import type { BrowserContext, Page } from '@playwright/test'

import { expect } from '../fixtures'

/**
 * Test-only Stellar wallet for Playwright.
 *
 * Playwright cannot drive the Freighter extension, so the app (built with
 * VITE_ENABLE_TEST_WALLET=true, dev/E2E only) looks for an injected
 * `window.__BOUNTYFLOW_TEST_WALLET__`. The page only ever sees the PUBLIC key:
 * signing is done here, in the test process, through `exposeFunction`, with
 * a fresh Friendbot-funded Testnet keypair per session. Nothing is mocked:
 * the API verifies real SEP-10 signatures and submits real Soroban
 * transactions to Stellar Testnet.
 */

export const TESTNET_PASSPHRASE = Networks.TESTNET
const FRIENDBOT = process.env.E2E_FRIENDBOT_URL ?? 'https://friendbot.stellar.org'
const HORIZON = process.env.E2E_HORIZON_URL ?? 'https://horizon-testnet.stellar.org'

export type TestWallet = { publicKey: string; keypair: Keypair }

/** Funds a Testnet account with Friendbot (retries transient failures). */
export async function fundWithFriendbot(publicKey: string): Promise<void> {
  let lastError: string
  for (let attempt = 1; attempt <= 4; attempt++) {
    try {
      const res = await fetch(`${FRIENDBOT}/?addr=${encodeURIComponent(publicKey)}`)
      if (res.ok) break
      const body = await res.text()
      // Already funded is fine (re-runs with the same key).
      if (res.status === 400 && /already|op_already_exists|createAccountAlreadyExist/i.test(body)) break
      lastError = `HTTP ${res.status}: ${body.slice(0, 200)}`
    } catch (e) {
      lastError = (e as Error).message
    }
    await new Promise((r) => setTimeout(r, attempt * 1500))
    if (attempt === 4) throw new Error(`Friendbot could not fund ${publicKey}: ${lastError}`)
  }
  // Wait until Horizon sees the account, so the API can load it for the challenge / transactions.
  await expect
    .poll(async () => (await fetch(`${HORIZON}/accounts/${publicKey}`)).status, {
      message: `account ${publicKey} visible on Horizon`,
      timeout: 60_000,
      intervals: [1000, 2000, 3000],
    })
    .toBe(200)
}

/**
 * Creates a fresh keypair, funds it, and installs it as the wallet for every
 * page of `target`'s browser context. Call before the first navigation.
 */
export async function installTestWallet(
  target: Page | BrowserContext,
  opts: { fund?: boolean; name?: string } = {},
): Promise<TestWallet> {
  const context = 'context' in target ? target.context() : target
  const keypair = Keypair.random()
  if (opts.fund !== false) await fundWithFriendbot(keypair.publicKey())

  await context.exposeFunction('__bfTestSign', (xdr: string) => {
    const tx = TransactionBuilder.fromXDR(xdr, TESTNET_PASSPHRASE)
    tx.sign(keypair)
    return tx.toXDR()
  })
  await context.addInitScript(
    ({ publicKey, passphrase, name }) => {
      const w = window as unknown as {
        __bfTestSign: (xdr: string) => Promise<string>
        __BOUNTYFLOW_TEST_WALLET__?: unknown
      }
      w.__BOUNTYFLOW_TEST_WALLET__ = {
        name,
        publicKey,
        network: 'TESTNET',
        networkPassphrase: passphrase,
        signTransaction: (xdr: string) => w.__bfTestSign(xdr),
      }
    },
    { publicKey: keypair.publicKey(), passphrase: TESTNET_PASSPHRASE, name: opts.name },
  )
  return { publicKey: keypair.publicKey(), keypair }
}

/**
 * Links the installed test wallet to the signed-in account through the UI:
 * the header wallet button → "Verify ownership" signs a real SEP-10 challenge.
 */
export async function verifyWalletViaUi(page: Page, wallet: TestWallet): Promise<void> {
  const short = `${wallet.publicKey.slice(0, 4)}…${wallet.publicKey.slice(-4)}`
  const trigger = page.getByRole('button', { name: 'Wallet menu' }).filter({ visible: true }).first()
  await expect(trigger).toContainText(short, { timeout: 20_000 })
  await trigger.click()
  await page.getByRole('menuitem', { name: 'Verify ownership' }).click()
  await expect(page.locator('[data-sonner-toast]').filter({ hasText: 'Wallet ownership verified by signature' }).first()).toBeVisible({
    timeout: 30_000,
  })
}
