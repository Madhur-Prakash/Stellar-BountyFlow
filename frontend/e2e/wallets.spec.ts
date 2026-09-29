import { Keypair, TransactionBuilder } from '@stellar/stellar-sdk'
import type { CDPSession, Page } from '@playwright/test'

import { apiCall, expect, signIn, test, uniqueSuffix } from './fixtures'
import { ADMIN, CONTRIBUTOR, REQUESTER } from './support/accounts'
import { signChainDialog } from './support/chain-ui'
import { acceptViaApi, applyViaApi, fundedBountyViaApi, linkWalletViaApi, newSession } from './support/flows'
import { installTestWallet, TESTNET_PASSPHRASE, fundWithFriendbot } from './support/wallet'

/**
 * Wallets on Stellar Testnet:
 *
 * 1. the wallet picker — installed wallets, install links, choosing one and proving ownership;
 * 2. a sponsored contributor transaction — the fee is paid by BountyFlow's sponsor account, which Horizon
 *    confirms as the transaction's fee account;
 * 3. a passkey smart wallet — created with Chromium's virtual WebAuthn authenticator (CDP), deployed by the
 *    sponsor and verified with a SEP-45 contract authorization.
 *
 * Nothing here is mocked: every signature is real and every transaction settles on Testnet.
 */

const HORIZON = process.env.E2E_HORIZON_URL ?? 'https://horizon-testnet.stellar.org'

type HorizonTx = { fee_account?: string; successful?: boolean; fee_charged?: string }

async function horizonTransaction(hash: string): Promise<HorizonTx> {
  let body: HorizonTx = {}
  await expect
    .poll(
      async () => {
        const res = await fetch(`${HORIZON}/transactions/${hash}`)
        if (!res.ok) return false
        body = (await res.json()) as HorizonTx
        return true
      },
      { message: `transaction ${hash} visible on Horizon`, timeout: 60_000, intervals: [1000, 2000, 3000] },
    )
    .toBe(true)
  return body
}

/** The sponsor account the API reports through the wallet options endpoint (null when sponsorship is off). */
async function sponsorAddress(page: Page): Promise<string | null> {
  const options = await apiCall<{ sponsorship: { enabled: boolean; sponsor_address: string | null } }>(
    page,
    'GET',
    '/wallets/options',
  )
  return options.sponsorship.enabled ? options.sponsorship.sponsor_address : null
}

test.describe('21. wallet picker', () => {
  test('lists wallets, connects the chosen one and proves ownership by signature', async ({ page }) => {
    // The E2E wallet is a kit-compatible module, so it appears in the picker like any other wallet.
    const wallet = await installTestWallet(page, { name: 'Test wallet', autoConnect: false })
    await signIn(page, REQUESTER)
    await page.goto('/app/profile')

    await page.getByRole('button', { name: 'Connect wallet' }).first().click()
    const picker = page.getByRole('dialog', { name: 'Connect a wallet' })
    await expect(picker).toBeVisible()
    await expect(picker.getByRole('heading', { name: 'Available' })).toBeVisible()
    // Wallets that are not installed are listed with an install link instead of a Connect button.
    await expect(picker.getByRole('link', { name: /install freighter/i })).toHaveAttribute(
      'href',
      'https://www.freighter.app/',
    )

    await picker.getByRole('button', { name: 'Connect Test wallet' }).click()
    await expect(picker).toBeHidden()
    const short = `${wallet.publicKey.slice(0, 4)}…${wallet.publicKey.slice(-4)}`
    const menu = page.getByRole('button', { name: 'Wallet menu' }).filter({ visible: true }).first()
    await expect(menu).toContainText(short, { timeout: 20_000 })

    await menu.click()
    await page.getByRole('menuitem', { name: 'Verify ownership' }).click()
    await expect(
      page
        .locator('[data-sonner-toast]')
        .filter({ hasText: 'Wallet ownership verified by signature' })
        .first(),
    ).toBeVisible({ timeout: 30_000 })

    const card = page.locator('[data-slot="card"]').filter({ hasText: 'Linked wallets' })
    await expect(card.getByText('Ownership verified by signature')).toBeVisible()
    await expect(card.getByText('Test wallet')).toBeVisible()
    await expect(card.getByText('Signed challenge transaction.')).toBeVisible()

    // The choice is remembered: a reload reconnects without the picker.
    await page.reload()
    await expect(
      page.getByRole('button', { name: 'Wallet menu' }).filter({ visible: true }).first(),
    ).toContainText(short, { timeout: 20_000 })
  })

  test('a wallet that only signs messages proves ownership with SEP-53', async ({ page }) => {
    const wallet = await installTestWallet(page, { name: 'Test wallet', proof: 'message' })
    await signIn(page, REQUESTER)
    await page.goto('/app/profile')

    const menu = page.getByRole('button', { name: 'Wallet menu' }).filter({ visible: true }).first()
    await expect(menu).toContainText(wallet.publicKey.slice(0, 4), { timeout: 20_000 })
    await menu.click()
    await page.getByRole('menuitem', { name: 'Verify ownership' }).click()
    await expect(
      page
        .locator('[data-sonner-toast]')
        .filter({ hasText: 'Wallet ownership verified by signature' })
        .first(),
    ).toBeVisible({ timeout: 30_000 })

    const card = page.locator('[data-slot="card"]').filter({ hasText: 'Linked wallets' })
    await expect(card.getByText('Signed message.')).toBeVisible()
    const wallets = await apiCall<{ public_address: string; proof_method: string }[]>(page, 'GET', '/wallets')
    expect(wallets.find((w) => w.public_address === wallet.publicKey)?.proof_method).toBe('sep53')
  })
})

test.describe('22. fee sponsorship', () => {
  test('BountyFlow pays the network fee of a contributor transaction', async ({
    page,
    browser,
    guard,
  }, info) => {
    test.setTimeout(300_000)
    const sponsor = await (async () => {
      const requesterWallet = await installTestWallet(page)
      await signIn(page, REQUESTER)
      await linkWalletViaApi(page, requesterWallet)
      const address = await sponsorAddress(page)
      test.skip(!address, 'This deployment has no fee sponsor configured (STELLAR_SPONSOR_SECRET).')
      return { address: address!, wallet: requesterWallet }
    })()

    // A funded bounty with an on-chain assignment: the contributor can then consent to a cancellation, which is
    // a contributor-side call and therefore eligible for sponsorship.
    const bounty = await fundedBountyViaApi(page, sponsor.wallet, {
      title: `E2E sponsored bounty ${uniqueSuffix()}`,
    })
    const contributor = await newSession(browser, info, guard, 'contributor')
    await signIn(contributor.page, CONTRIBUTOR)
    await linkWalletViaApi(contributor.page, contributor.wallet!)
    const application = await applyViaApi(contributor.page, bounty.id)
    const accepted = await acceptViaApi(page, application.id)
    await apiCall(page, 'POST', `/bounties/${bounty.id}/chain/prepare`, {
      action: 'ASSIGN',
      wallet_address: sponsor.wallet.publicKey,
      assignment_id: accepted.assignment_id,
    })

    // The contributor's own balance before signing: a sponsored fee must not touch it.
    const before = await horizonAccountBalance(contributor.wallet!.publicKey)

    const prepared = await apiCall<{
      transaction: { id: string }
      unsigned_xdr: string
      summary: { fee_sponsored: boolean }
    }>(contributor.page, 'POST', `/bounties/${bounty.id}/chain/prepare`, {
      action: 'CONSENT_CANCEL',
      wallet_address: contributor.wallet!.publicKey,
    })
    expect(prepared.summary.fee_sponsored, 'the API offers to pay this fee').toBe(true)

    const envelope = TransactionBuilder.fromXDR(prepared.unsigned_xdr, TESTNET_PASSPHRASE)
    envelope.sign(contributor.wallet!.keypair)
    const tx = await apiCall<{ id: string; transaction_hash: string }>(
      contributor.page,
      'POST',
      `/transactions/${prepared.transaction.id}/submit`,
      { signed_xdr: envelope.toXDR() },
    )
    await expect
      .poll(
        async () =>
          (await apiCall<{ status: string }>(contributor.page, 'GET', `/transactions/${tx.id}`)).status,
        { message: 'sponsored transaction confirmed', timeout: 120_000, intervals: [2000, 3000] },
      )
      .toBe('CONFIRMED')

    // Horizon is the proof: the fee account of the included transaction is the platform sponsor.
    const onchain = await horizonTransaction(tx.transaction_hash)
    expect(onchain.successful).toBe(true)
    expect(onchain.fee_account).toBe(sponsor.address)
    expect(await horizonAccountBalance(contributor.wallet!.publicKey)).toBe(before)

    const detail = await apiCall<{ fee_sponsored: boolean }>(
      contributor.page,
      'GET',
      `/transactions/${tx.id}`,
    )
    expect(detail.fee_sponsored).toBe(true)
  })

  test('the admin overview shows the sponsor balance and recent sponsored transactions', async ({ page }) => {
    await signIn(page, ADMIN)
    await page.goto('/admin')
    const card = page.locator('[data-slot="card"]').filter({ hasText: 'Fee sponsorship' })
    await expect(card).toBeVisible()
    await expect(card.getByText('Balance')).toBeVisible()
    await expect(card.getByText('Fees today')).toBeVisible()
  })
})

/** XLM balance of a Testnet account, as Horizon reports it. */
async function horizonAccountBalance(address: string): Promise<string> {
  const res = await fetch(`${HORIZON}/accounts/${address}`)
  const body = (await res.json()) as { balances?: { asset_type: string; balance: string }[] }
  return body.balances?.find((b) => b.asset_type === 'native')?.balance ?? '0'
}

test.describe('23. passkey smart wallet', () => {
  test('creates a passkey wallet, deploys it through the sponsor and verifies it with SEP-45', async ({
    page,
    context,
  }) => {
    test.setTimeout(300_000)
    // Chromium's virtual authenticator: WebAuthn ceremonies complete without user interaction, and the
    // credential is a real secp256r1 key the smart wallet contract verifies on-chain.
    const cdp: CDPSession = await context.newCDPSession(page)
    await cdp.send('WebAuthn.enable')
    const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', {
      options: {
        protocol: 'ctap2',
        ctap2Version: 'ctap2_1',
        transport: 'internal',
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
        automaticPresenceSimulation: true,
      },
    })

    await signIn(page, REQUESTER)
    const sponsor = await sponsorAddress(page)
    test.skip(!sponsor, 'This deployment has no fee sponsor configured, so passkey wallets are off.')

    await page.goto('/app/profile#passkey')
    const card = page.locator('[data-slot="card"]').filter({ hasText: 'Passkey wallet' })
    await expect(card).toBeVisible()
    await card.getByRole('button', { name: 'Create a passkey wallet' }).click()
    await expect(
      page.locator('[data-sonner-toast]').filter({ hasText: 'Passkey wallet created' }).first(),
    ).toBeVisible({ timeout: 120_000 })

    // The deployment is confirmed on-chain before the wallet is shown as created.
    await expect(card.getByText('Created, not verified yet')).toBeVisible({ timeout: 120_000 })
    const wallets = await apiCall<{ contract_id: string; status: string; deploy_tx_hash: string }[]>(
      page,
      'GET',
      '/wallets/passkey',
    )
    const wallet = wallets[0]!
    expect(wallet.status).toBe('ACTIVE')
    expect(wallet.contract_id.startsWith('C')).toBe(true)
    const deployment = await horizonTransaction(wallet.deploy_tx_hash)
    expect(deployment.successful).toBe(true)
    expect(deployment.fee_account, 'the sponsor pays for the deployment').toBe(sponsor)

    // SEP-45: the wallet authorizes the challenge with its passkey; the API verifies it by simulation.
    await card.getByRole('button', { name: 'Verify ownership' }).click()
    await expect(
      page
        .locator('[data-sonner-toast]')
        .filter({ hasText: 'Wallet ownership verified by signature' })
        .first(),
    ).toBeVisible({ timeout: 120_000 })

    const linked = await apiCall<{ public_address: string; proof_method: string; wallet_app: string }[]>(
      page,
      'GET',
      '/wallets',
    )
    const row = linked.find((w) => w.public_address === wallet.contract_id)
    expect(row?.proof_method).toBe('sep45')
    expect(row?.wallet_app).toBe('passkey')

    // The linked smart wallet can be used as the payout wallet like any other.
    const walletsCard = page.locator('[data-slot="card"]').filter({ hasText: 'Linked wallets' })
    await walletsCard
      .locator('li')
      .filter({ hasText: wallet.contract_id.slice(0, 6) })
      .getByRole('button', { name: 'Use for payouts' })
      .click()
    await expect(
      page.locator('[data-sonner-toast]').filter({ hasText: 'Payouts now go to this wallet' }).first(),
    ).toBeVisible()

    await cdp.send('WebAuthn.removeVirtualAuthenticator', { authenticatorId })
  })

  test('a smart wallet funds a bounty through the sponsor and receives a payout', async ({
    page,
    browser,
    guard,
  }, info) => {
    test.setTimeout(420_000)
    const cdp = await page.context().newCDPSession(page)
    await cdp.send('WebAuthn.enable')
    await cdp.send('WebAuthn.addVirtualAuthenticator', {
      options: {
        protocol: 'ctap2',
        transport: 'internal',
        hasResidentKey: true,
        hasUserVerification: true,
        isUserVerified: true,
        automaticPresenceSimulation: true,
      },
    })
    await signIn(page, REQUESTER)
    test.skip(!(await sponsorAddress(page)), 'This deployment has no fee sponsor configured.')

    // A passkey wallet needs the reward to fund a bounty; Friendbot cannot fund a contract, so the requester's
    // funded account sends it there first.
    await page.goto('/app/profile#passkey')
    const card = page.locator('[data-slot="card"]').filter({ hasText: 'Passkey wallet' })
    await card.getByRole('button', { name: 'Create a passkey wallet' }).click()
    await expect(
      page.locator('[data-sonner-toast]').filter({ hasText: 'Passkey wallet created' }).first(),
    ).toBeVisible({ timeout: 120_000 })
    await card.getByRole('button', { name: 'Verify ownership' }).click()
    await expect(
      page
        .locator('[data-sonner-toast]')
        .filter({ hasText: 'Wallet ownership verified by signature' })
        .first(),
    ).toBeVisible({ timeout: 120_000 })
    const [smartWallet] = await apiCall<{ contract_id: string }[]>(page, 'GET', '/wallets/passkey')

    const funder = Keypair.random()
    await fundWithFriendbot(funder.publicKey())
    await sendXlmToContract(funder, smartWallet!.contract_id, '60')

    // The contributor is paid to their own passkey wallet: a C-address payout destination.
    const contributor = await newSession(browser, info, guard, 'contributor', { wallet: false })
    await signIn(contributor.page, CONTRIBUTOR)
    const contributorWallet = await installTestWallet(contributor.page)
    await linkWalletViaApi(contributor.page, contributorWallet)

    const bounty = await apiCall<{ id: string }>(page, 'POST', '/bounties', {
      title: `E2E passkey funded bounty ${uniqueSuffix()}`,
      short_description: 'A bounty funded from a passkey smart wallet in the end-to-end suite.',
      description: 'The requester funds this bounty from a Soroban smart wallet secured by a passkey.',
      category: 'DEVELOPMENT',
      difficulty: 'BEGINNER',
      reward_amount: '2',
      positions_available: 1,
      acceptance_criteria: 'The escrow is funded from the smart wallet.',
    })
    await apiCall(page, 'POST', `/bounties/${bounty.id}/publish`)

    await page.goto(`/app/bounties/${bounty.id}`)
    await page.getByRole('button', { name: 'Fund escrow' }).click()
    const dialog = page.getByRole('dialog', { name: /fund escrow/i })
    await expect(dialog.getByText('Network fee paid by BountyFlow')).toBeVisible({ timeout: 60_000 })
    await signChainDialog(page, /fund escrow/i)

    await expect
      .poll(async () => (await apiCall<{ status: string }>(page, 'GET', `/bounties/${bounty.id}`)).status, {
        message: 'the escrow is funded from the smart wallet',
        timeout: 120_000,
      })
      .toBe('FUNDED')
  })
})

/** Sends XLM from a funded account to a contract address through the native asset contract. */
async function sendXlmToContract(from: Keypair, contractId: string, amount: string): Promise<void> {
  const {
    Contract,
    nativeToScVal,
    rpc,
    TransactionBuilder: Builder,
    Address,
  } = await import('@stellar/stellar-sdk')
  const server = new rpc.Server(process.env.E2E_SOROBAN_RPC_URL ?? 'https://soroban-testnet.stellar.org')
  const native = new Contract(
    (await apiCall2<{ native_asset_contract_id: string }>('/config/public')).native_asset_contract_id,
  )
  const account = await server.getAccount(from.publicKey())
  const tx = new Builder(account, { fee: '1000000', networkPassphrase: TESTNET_PASSPHRASE })
    .addOperation(
      native.call(
        'transfer',
        new Address(from.publicKey()).toScVal(),
        new Address(contractId).toScVal(),
        nativeToScVal(BigInt(Number(amount) * 10_000_000), { type: 'i128' }),
      ),
    )
    .setTimeout(120)
    .build()
  const prepared = await server.prepareTransaction(tx)
  prepared.sign(from)
  const sent = await server.sendTransaction(prepared)
  await expect
    .poll(async () => (await server.getTransaction(sent.hash)).status, {
      message: 'the smart wallet received XLM',
      timeout: 90_000,
      intervals: [2000, 3000],
    })
    .toBe('SUCCESS')
}

/** Public config read without a session (the E2E API base is proxied by Vite). */
async function apiCall2<T>(path: string): Promise<T> {
  const base = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
  const res = await fetch(`${base}/api/v1${path}`)
  return (await res.json()) as T
}
