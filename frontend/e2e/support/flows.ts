import { TransactionBuilder } from '@stellar/stellar-sdk'
import type { Browser, Page, TestInfo } from '@playwright/test'

import { apiCall, expect, uniqueSuffix } from '../fixtures'
import { installTestWallet, TESTNET_PASSPHRASE, type TestWallet } from './wallet'

/**
 * API shortcuts for *setting up* state that a journey is not about (e.g. a
 * funded bounty for the dispute journey). Every chain action is real: the
 * transaction is prepared by the API, signed here with the session's Testnet
 * keypair, submitted, and confirmed on Stellar Testnet. Journeys that test a
 * flow drive it through the UI instead.
 */

export type Bounty = {
  id: string
  slug: string
  title: string
  status: string
  funding_status: string
  escrow: { state: string } | null
}
type Tx = { id: string; status: string; bounty_id: string | null; transaction_hash: string | null; failure_reason: string | null }
type Prepared = { transaction: Tx; unsigned_xdr: string; network_passphrase: string }

function sign(xdr: string, wallet: TestWallet): string {
  const tx = TransactionBuilder.fromXDR(xdr, TESTNET_PASSPHRASE)
  tx.sign(wallet.keypair)
  return tx.toXDR()
}

/** Proves ownership of `wallet` for the signed-in account (real SEP-10 challenge). */
export async function linkWalletViaApi(page: Page, wallet: TestWallet): Promise<void> {
  const challenge = await apiCall<{ challenge_xdr: string }>(page, 'POST', '/wallets/challenge', {
    public_address: wallet.publicKey,
  })
  await apiCall(page, 'POST', '/wallets/verify', {
    public_address: wallet.publicKey,
    signed_challenge_xdr: sign(challenge.challenge_xdr, wallet),
  })
}

export async function createBountyViaApi(page: Page, overrides: Record<string, unknown> = {}): Promise<Bounty> {
  const s = uniqueSuffix()
  return apiCall<Bounty>(page, 'POST', '/bounties', {
    title: `E2E setup bounty ${s}`,
    short_description: 'An end-to-end test bounty created through the API for setup.',
    description:
      'This bounty exists so an end-to-end journey has a realistic starting point. It is created by the Playwright suite.',
    category: 'DOCUMENTATION',
    difficulty: 'BEGINNER',
    tags: ['e2e'],
    required_skills: ['testing'],
    reward_amount: '2',
    positions_available: 1,
    acceptance_criteria: 'The journey under test completes successfully.',
    ...overrides,
  })
}

/** prepare → sign with the session wallet → submit → wait for CONFIRMED on Testnet. */
export async function chainActionViaApi(
  page: Page,
  bountyId: string,
  body: Record<string, unknown>,
  wallet: TestWallet,
): Promise<Tx> {
  const prepared = await apiCall<Prepared>(page, 'POST', `/bounties/${bountyId}/chain/prepare`, {
    ...body,
    wallet_address: wallet.publicKey,
  })
  let tx = await apiCall<Tx>(page, 'POST', `/transactions/${prepared.transaction.id}/submit`, {
    signed_xdr: sign(prepared.unsigned_xdr, wallet),
  })
  await expect
    .poll(
      async () => {
        tx = await apiCall<Tx>(page, 'GET', `/transactions/${tx.id}`)
        return tx.status
      },
      { message: `transaction ${tx.id} confirmed on Testnet`, timeout: 90_000, intervals: [2000, 3000] },
    )
    .toBe('CONFIRMED')
  return tx
}

export async function fundedBountyViaApi(page: Page, wallet: TestWallet, overrides: Record<string, unknown> = {}): Promise<Bounty> {
  const bounty = await createBountyViaApi(page, overrides)
  await apiCall(page, 'POST', `/bounties/${bounty.id}/publish`)
  await chainActionViaApi(page, bounty.id, { action: 'FUND' }, wallet)
  await expect
    .poll(async () => (await apiCall<Bounty>(page, 'GET', `/bounties/${bounty.id}`)).status, { timeout: 30_000 })
    .toBe('FUNDED')
  return apiCall<Bounty>(page, 'GET', `/bounties/${bounty.id}`)
}

export async function applyViaApi(page: Page, bountyId: string): Promise<{ id: string }> {
  return apiCall(page, 'POST', `/bounties/${bountyId}/applications`, {
    cover_message: 'I can deliver this quickly and have done similar work before. (E2E setup)',
  })
}

export async function acceptViaApi(page: Page, applicationId: string): Promise<{ id: string; assignment_id: string | null }> {
  return apiCall(page, 'POST', `/applications/${applicationId}/accept`, {})
}

/**
 * A second, independent browser session (another user) with its own funded
 * Testnet wallet, watched by the runtime guard.
 */
export async function newSession(
  browser: Browser,
  testInfo: TestInfo,
  guard: { watch: (page: Page, label?: string) => void },
  label: string,
  opts: { wallet?: boolean } = {},
): Promise<{ page: Page; wallet: TestWallet | null }> {
  const use = testInfo.project.use
  const context = await browser.newContext({
    baseURL: use.baseURL,
    viewport: use.viewport ?? { width: 1280, height: 800 },
    colorScheme: 'light',
  })
  const wallet = opts.wallet === false ? null : await installTestWallet(context)
  const page = await context.newPage()
  guard.watch(page, label)
  return { page, wallet }
}
