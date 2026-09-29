import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { Keypair, TransactionBuilder } from '@stellar/stellar-sdk'
import type { Browser, Page, TestInfo } from '@playwright/test'

import { apiCall, expect } from '../fixtures'
import { chainActionViaApi, linkWalletViaApi, type Bounty } from './flows'
import { fundWithFriendbot, TESTNET_PASSPHRASE, type TestWallet } from './wallet'

/**
 * Setup helpers for the escrow v2 journeys (milestones, batch payouts, the review clock and the M-of-N arbiter
 * set). Like `flows.ts`, every chain action is a real Testnet transaction signed in the test process.
 */

export type EscrowConfig = {
  contract_id: string | null
  contract_version: number
  default_review_window_seconds: number
  min_review_window_seconds: number
  max_review_window_seconds: number
  arbiter_addresses: string[]
  arbiter_threshold: number
  max_milestones: number
  max_batch: number
}

export type Submission = {
  id: string
  status: string
  payment: { payment_status: string; amount: string } | null
  onchain_review: { state: string; claimable_at: string | null; can_claim: boolean } | null
}

export function escrowConfig(page: Page): Promise<EscrowConfig> {
  return apiCall<EscrowConfig>(page, 'GET', '/escrow/config')
}

/**
 * Secret keys of the Testnet arbiter wallets the suite may sign with (E2E_ARBITER_SECRETS, comma separated). Read
 * from the environment, or from the repository's root .env when the suite runs next to it. The keys stay in the
 * test process: the page only sees the public keys.
 */
export function arbiterKeypairs(): Keypair[] {
  let raw = process.env.E2E_ARBITER_SECRETS
  if (!raw) {
    try {
      const env = readFileSync(resolve(process.cwd(), '..', '.env'), 'utf8')
      raw = env.match(/^E2E_ARBITER_SECRETS=(.*)$/m)?.[1]?.trim()
    } catch {
      raw = undefined
    }
  }
  return (raw ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Keypair.fromSecret(s))
}

/**
 * A browser session that signs with a known keypair (an arbiter wallet) instead of a fresh random one.
 * Mirrors `installTestWallet` in wallet.ts.
 */
export async function sessionWithKeypair(
  browser: Browser,
  testInfo: TestInfo,
  guard: { watch: (page: Page, label?: string) => void },
  label: string,
  keypair: Keypair,
): Promise<{ page: Page; wallet: TestWallet }> {
  const use = testInfo.project.use
  const context = await browser.newContext({
    baseURL: use.baseURL,
    viewport: use.viewport ?? { width: 1280, height: 800 },
    colorScheme: 'light',
    reducedMotion: 'reduce',
  })
  // Fees for the vote come from the arbiter wallet; top it up if Friendbot still can.
  await fundWithFriendbot(keypair.publicKey())
  await context.exposeFunction('__bfTestSign', (xdr: string) => {
    const tx = TransactionBuilder.fromXDR(xdr, TESTNET_PASSPHRASE)
    tx.sign(keypair)
    return tx.toXDR()
  })
  await context.addInitScript(
    ({ publicKey, passphrase }) => {
      const w = window as unknown as {
        __bfTestSign: (xdr: string) => Promise<string>
        __BOUNTYFLOW_TEST_WALLET__?: unknown
      }
      w.__BOUNTYFLOW_TEST_WALLET__ = {
        publicKey,
        network: 'TESTNET',
        networkPassphrase: passphrase,
        signTransaction: (xdr: string) => w.__bfTestSign(xdr),
      }
    },
    { publicKey: keypair.publicKey(), passphrase: TESTNET_PASSPHRASE },
  )
  const page = await context.newPage()
  guard.watch(page, label)
  return { page, wallet: { publicKey: keypair.publicKey(), keypair } }
}

/** Verifies `wallet` on the signed-in account unless it already is (re-runs against the same database). */
export async function ensureWalletLinked(page: Page, wallet: TestWallet): Promise<void> {
  const wallets = await apiCall<{ public_address: string }[]>(page, 'GET', '/wallets')
  if (wallets.some((w) => w.public_address === wallet.publicKey)) return
  await linkWalletViaApi(page, wallet)
}

/** Records the accepted contributor's assignment in the escrow (ASSIGN, signed by the requester). */
export async function assignOnchainViaApi(
  requester: Page,
  bountyId: string,
  assignmentId: string,
  wallet: TestWallet,
): Promise<void> {
  await chainActionViaApi(requester, bountyId, { action: 'ASSIGN', assignment_id: assignmentId }, wallet)
}

export async function submitWorkViaApi(
  contributor: Page,
  bountyId: string,
  description: string,
  milestoneId?: string,
): Promise<Submission> {
  return apiCall<Submission>(contributor, 'POST', `/bounties/${bountyId}/submissions`, {
    description,
    evidence_links: [],
    pull_request_urls: [],
    ...(milestoneId ? { milestone_id: milestoneId } : {}),
  })
}

export function approveViaApi(requester: Page, submissionId: string): Promise<Submission> {
  return apiCall<Submission>(requester, 'POST', `/submissions/${submissionId}/approve`, {})
}

export function getBounty(page: Page, bountyId: string): Promise<Bounty> {
  return apiCall<Bounty>(page, 'GET', `/bounties/${bountyId}`)
}

/** Waits until the contract's review window for `submissionId` has passed, with a margin for ledger close time. */
export async function waitForClaimWindow(contributor: Page, submissionId: string): Promise<void> {
  let claimableAt = 0
  await expect
    .poll(
      async () => {
        const s = await apiCall<Submission>(contributor, 'GET', `/submissions/${submissionId}`)
        claimableAt = s.onchain_review?.claimable_at ? Date.parse(s.onchain_review.claimable_at) : 0
        return s.onchain_review?.can_claim ?? false
      },
      { message: 'review window passed', timeout: 240_000, intervals: [5000] },
    )
    .toBe(true)
  // Ledgers close every ~5 s, so the contract's clock can trail the server's by a few seconds.
  await expect
    .poll(() => Date.now() > claimableAt + 12_000, { timeout: 30_000, intervals: [2000] })
    .toBe(true)
}
