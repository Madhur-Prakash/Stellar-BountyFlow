import type { Page } from '@playwright/test'

import {
  apiCall,
  expect,
  newUser,
  registerViaApi,
  signIn,
  test,
  uniqueSuffix,
  type NewUser,
} from './fixtures'
import { ADMIN, MODERATOR, REQUESTER } from './support/accounts'
import { EXPLORER_TX, signChainDialog } from './support/chain-ui'
import {
  approveViaApi,
  arbiterKeypairs,
  assignOnchainViaApi,
  ensureWalletLinked,
  escrowConfig,
  sessionWithKeypair,
  submitWorkViaApi,
  waitForClaimWindow,
  type Submission,
} from './support/escrow-v2'
import {
  acceptViaApi,
  applyViaApi,
  chainActionViaApi,
  fundedBountyViaApi,
  linkWalletViaApi,
  newSession,
} from './support/flows'
import { installTestWallet } from './support/wallet'

/**
 * Escrow v2 journeys on Stellar Testnet, against the v2 contract (`version() == 2`):
 *
 * - V2-1: a bounty paid in two milestones; the first approved milestone is released on its own.
 * - V2-2: one batch transaction pays two contributors.
 * - V2-3: the contributor records work on-chain, the requester does not answer, and the contributor claims after
 *   the review window (needs ESCROW_MIN_REVIEW_WINDOW_SECONDS <= 120 on the API under test).
 * - V2-4: a 2-of-3 arbiter set executes a split decision (needs STELLAR_ARBITER_ADDRESSES with three addresses,
 *   STELLAR_ARBITER_THRESHOLD=2 and E2E_ARBITER_SECRETS holding two of those arbiters' secret keys).
 */

type Milestone = { id: string; position: number; title: string; amount: string; status: string }
type Detail = { id: string; slug: string; status: string; milestones?: Milestone[] }

test('V2-1. milestones: split the reward, fund once, release the first approved milestone', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(600_000)
  const requester = page
  const title = `E2E milestone bounty ${uniqueSuffix()}`
  const requesterWallet = await installTestWallet(requester)
  await signIn(requester, REQUESTER)
  const config = await escrowConfig(requester)
  test.skip(config.contract_version < 2, 'The API under test is not configured with the v2 escrow contract.')
  await linkWalletViaApi(requester, requesterWallet)
  let bountyId = ''

  await test.step('requester splits a 3 XLM reward into two milestones in the bounty form', async () => {
    await requester.goto('/app/bounties/create')
    await requester.getByLabel('Title', { exact: true }).fill(title)
    await requester.getByLabel('Summary').fill('Ship the escrow v2 milestone journey in two reviewed steps.')
    await requester
      .getByLabel('Full description')
      .fill(
        '## Scope\n\nDeliver the design first, then the implementation. Each step is reviewed and paid on its own.',
      )
    await requester.getByLabel('Reward per position (XLM)').fill('3')
    await requester.getByLabel('Positions', { exact: true }).fill('1')
    await requester.getByLabel('Required skills').fill('soroban, testing')
    await requester.getByLabel('Acceptance criteria').fill('- Design approved\n- Implementation merged')

    await requester.getByRole('switch', { name: 'Pay in milestones' }).click()
    await requester.getByLabel('Milestone 1', { exact: true }).fill('Design approved')
    await requester.getByLabel('Milestone 2', { exact: true }).fill('Implementation merged')
    const amounts = requester.getByLabel('Amount (XLM)')
    await amounts.nth(0).fill('1')
    await amounts.nth(1).fill('1')
    await expect(requester.getByText('1 XLM left to assign')).toBeVisible()
    await requester.getByRole('button', { name: 'Save draft' }).click()
    await expect(requester.getByText('The milestones must add up to the reward.')).toBeVisible()
    await amounts.nth(1).fill('2')
    await expect(requester.getByText('Adds up to 3 XLM')).toBeVisible()
    await requester.getByRole('button', { name: 'Save draft' }).click()
    await expect(requester).toHaveURL(/\/app\/bounties\/[0-9a-f-]{36}$/)
    bountyId = requester.url().split('/').pop()!
  })

  await test.step('requester publishes and funds the whole reward once', async () => {
    await requester.getByRole('button', { name: 'Publish' }).click()
    await expect(requester.getByText('Status: Open').first()).toBeVisible()
    await requester.getByRole('button', { name: 'Fund escrow' }).click()
    await expect(
      requester.getByRole('dialog', { name: /fund escrow/i }).getByText('3 XLM', { exact: true }),
    ).toBeVisible({
      timeout: 60_000,
    })
    await signChainDialog(requester, /fund escrow/i)
    await expect(requester.getByText('Status: Funded').first()).toBeVisible({ timeout: 30_000 })
  })

  const detail = await apiCall<Detail>(requester, 'GET', `/bounties/${bountyId}`)
  expect(detail.milestones?.map((m) => [m.title, m.status])).toEqual([
    ['Design approved', 'OPEN'],
    ['Implementation merged', 'OPEN'],
  ])

  // Setup: an accepted contributor, assigned on-chain.
  const { page: contributor, wallet: contributorWallet } = await newSession(
    browser,
    testInfo,
    guard,
    'contributor',
  )
  await registerViaApi(contributor, newUser('mile'))
  await linkWalletViaApi(contributor, contributorWallet!)
  const application = await applyViaApi(contributor, bountyId)
  const accepted = await acceptViaApi(requester, application.id)
  await assignOnchainViaApi(requester, bountyId, accepted.assignment_id!, requesterWallet)

  await test.step('contributor sees the milestones and submits work for the first one', async () => {
    await contributor.goto(`/bounties/${detail.slug}`)
    const list = contributor.getByRole('list', { name: 'Milestones' })
    await expect(list.getByRole('listitem')).toHaveCount(2)
    await expect(list.getByRole('listitem').first()).toContainText('Design approved')
    await expect(list.getByRole('listitem').first()).toContainText('Open')
    await expect(contributor.getByText('0 of 2 paid')).toBeVisible()

    await contributor.getByRole('button', { name: 'Submit work' }).click()
    const dialog = contributor.getByRole('dialog', { name: 'Submit your work' })
    await dialog
      .getByLabel('What you delivered')
      .fill('The escrow v2 design, reviewed against the acceptance criteria.')
    await dialog.getByRole('button', { name: 'Submit work' }).click()
    await expect(dialog.getByText('Choose the milestone this work is for.')).toBeVisible()
    await dialog.getByRole('combobox', { name: 'Milestone' }).click()
    await contributor.getByRole('option', { name: /1\. Design approved \(1 XLM\)/ }).click()
    await dialog.getByRole('button', { name: 'Submit work' }).click()
    await expect(dialog).toBeHidden()
  })

  await test.step('requester approves the milestone and releases 1 XLM on Testnet', async () => {
    await requester.goto(`/app/bounties/${bountyId}/submissions`)
    const card = requester.getByRole('listitem').filter({ hasText: 'Milestone 1: Design approved' })
    await card.getByRole('button', { name: 'Approve' }).click()
    const dialog = requester.getByRole('dialog', { name: /approve this submission/i })
    await dialog.getByRole('button', { name: 'Approve' }).click()
    await expect(dialog).toBeHidden()
    await card.getByRole('button', { name: 'Pay milestone 1 XLM' }).click()
    await signChainDialog(requester, /release milestone/i)
    await expect(card.getByText('Confirmed', { exact: true }).first()).toBeVisible({ timeout: 30_000 })
  })

  await test.step('the first milestone reads paid; the bounty stays open for the second', async () => {
    await contributor.goto(`/bounties/${detail.slug}`)
    const items = contributor.getByRole('list', { name: 'Milestones' }).getByRole('listitem')
    await expect(items.first()).toContainText('Paid')
    await expect(items.first().getByRole('link', { name: /payout transaction/i })).toHaveAttribute(
      'href',
      EXPLORER_TX,
    )
    await expect(items.nth(1)).toContainText('Open')
    await expect(contributor.getByText('1 of 2 paid')).toBeVisible()
    await expect(contributor.getByText('Status: Completed')).toHaveCount(0)
    // The second milestone can still be delivered.
    await expect(contributor.getByRole('button', { name: 'Submit work' })).toBeVisible()
    const after = await apiCall<Detail>(contributor, 'GET', `/bounties/${bountyId}`)
    expect(after.milestones?.map((m) => m.status)).toEqual(['PAID', 'OPEN'])
  })

  await contributor.context().close()
})

test('V2-2. batch payout: one transaction pays two contributors', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(600_000)
  const requester = page
  const title = `E2E batch bounty ${uniqueSuffix()}`
  const requesterWallet = await installTestWallet(requester)
  await signIn(requester, REQUESTER)
  const config = await escrowConfig(requester)
  test.skip(config.contract_version < 2, 'The API under test is not configured with the v2 escrow contract.')
  await linkWalletViaApi(requester, requesterWallet)
  const bounty = await fundedBountyViaApi(requester, requesterWallet, {
    title,
    reward_amount: '1',
    positions_available: 2,
  })

  // Setup: two accepted contributors, assigned on-chain, whose work is approved.
  const contributors: { page: Page; user: NewUser; submission: Submission }[] = []
  for (const label of ['batch-a', 'batch-b']) {
    const { page: p, wallet } = await newSession(browser, testInfo, guard, label)
    const user = await registerViaApi(p, newUser(label))
    await linkWalletViaApi(p, wallet!)
    const application = await applyViaApi(p, bounty.id)
    const accepted = await acceptViaApi(requester, application.id)
    await assignOnchainViaApi(requester, bounty.id, accepted.assignment_id!, requesterWallet)
    const submission = await submitWorkViaApi(
      p,
      bounty.id,
      `Delivered by ${user.displayName} for the batch payout journey.`,
    )
    await approveViaApi(requester, submission.id)
    contributors.push({ page: p, user, submission })
  }

  await test.step('requester selects both approved payouts and signs one batch transaction', async () => {
    await requester.goto(`/app/bounties/${bounty.id}/submissions`)
    for (const c of contributors) {
      await requester
        .getByRole('checkbox', { name: `Select ${c.user.displayName}'s payout for a batch payment` })
        .check()
    }
    const bar = requester.getByRole('region', { name: 'Batch payout' })
    await expect(bar).toContainText('2 selected')
    await expect(bar).toContainText('2 XLM')
    await bar.getByRole('button', { name: 'Pay 2 contributors' }).click()
    await signChainDialog(requester, /batch payout/i)
  })

  await test.step('both legs are verified on-chain before either reads paid', async () => {
    for (const c of contributors) {
      await expect
        .poll(
          async () =>
            (await apiCall<Submission>(requester, 'GET', `/submissions/${c.submission.id}`)).payment
              ?.payment_status,
          { timeout: 60_000 },
        )
        .toBe('CONFIRMED')
    }
    await requester.goto(`/app/bounties/${bounty.id}`)
    await expect(requester.getByText('Status: Completed').first()).toBeVisible({ timeout: 30_000 })

    await requester.goto('/app/transactions')
    const batch = requester.getByRole('row').filter({ hasText: title }).filter({ hasText: 'Batch payout' })
    await expect(batch).toHaveCount(1)
    await expect(batch.getByText('Confirmed')).toBeVisible()
    await expect(batch.getByRole('link', { name: /view on explorer/i })).toHaveAttribute('href', EXPLORER_TX)

    for (const c of contributors) {
      await c.page.goto('/app/payments')
      const received = c.page.getByRole('row').filter({ hasText: title })
      await expect(received.getByText('Confirmed')).toBeVisible()
    }
  })

  for (const c of contributors) await c.page.context().close()
})

test('V2-3. review timeout: the contributor records work on-chain and claims after the window', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(720_000)
  const requester = page
  const title = `E2E claim bounty ${uniqueSuffix()}`
  const requesterWallet = await installTestWallet(requester)
  await signIn(requester, REQUESTER)
  const config = await escrowConfig(requester)
  test.skip(config.contract_version < 2, 'The API under test is not configured with the v2 escrow contract.')
  test.skip(
    config.min_review_window_seconds > 120,
    'Needs a short review window: start the API with ESCROW_MIN_REVIEW_WINDOW_SECONDS=60.',
  )
  await linkWalletViaApi(requester, requesterWallet)
  const bounty = await fundedBountyViaApi(requester, requesterWallet, {
    title,
    reward_amount: '1.5',
    review_window_seconds: config.min_review_window_seconds,
  })

  const { page: contributor, wallet } = await newSession(browser, testInfo, guard, 'contributor')
  await registerViaApi(contributor, newUser('claim'))
  await linkWalletViaApi(contributor, wallet!)
  const application = await applyViaApi(contributor, bounty.id)
  const accepted = await acceptViaApi(requester, application.id)
  await assignOnchainViaApi(requester, bounty.id, accepted.assignment_id!, requesterWallet)
  const submission = await submitWorkViaApi(
    contributor,
    bounty.id,
    'Delivered work that the requester does not answer within the review window.',
  )

  await test.step('contributor records the submission on-chain; the review clock starts', async () => {
    await contributor.goto('/app/submissions')
    const row = contributor.getByRole('row').filter({ hasText: title })
    await row.getByRole('button', { name: 'Record on-chain' }).click()
    await signChainDialog(contributor, /record submission/i)
    await expect(row.getByText(/claim in/i)).toBeVisible({ timeout: 30_000 })
    await expect(row.getByRole('button', { name: 'Claim payment' })).toHaveCount(0)
  })

  await test.step('requester sees the clock; a revision request now has to be signed on-chain', async () => {
    await requester.goto(`/app/bounties/${bounty.id}/submissions`)
    const card = requester
      .getByRole('listitem')
      .filter({ hasText: 'does not answer within the review window' })
    await expect(card.getByText(/recorded on-chain\. answer within/i)).toBeVisible()
    await card.getByRole('button', { name: 'Request revision' }).click()
    const dialog = requester.getByRole('dialog', { name: 'Request a revision' })
    await expect(dialog.getByText(/sign the request with your wallet/i)).toBeVisible()
    await requester.keyboard.press('Escape')
    await expect(dialog).toBeHidden()
  })

  await test.step('after the window, the contributor claims the payment from escrow', async () => {
    await waitForClaimWindow(contributor, submission.id)
    await contributor.goto('/app/submissions')
    const row = contributor.getByRole('row').filter({ hasText: title })
    await row.getByRole('button', { name: 'Claim payment' }).click()
    await signChainDialog(contributor, /claim payment/i)
    await expect
      .poll(
        async () =>
          (await apiCall<Submission>(contributor, 'GET', `/submissions/${submission.id}`)).payment
            ?.payment_status,
        { timeout: 60_000 },
      )
      .toBe('CONFIRMED')
    await contributor.goto('/app/payments')
    const received = contributor.getByRole('row').filter({ hasText: title })
    await expect(received.getByText('Confirmed')).toBeVisible()
    await expect(received.getByText('1.5')).toBeVisible()

    await requester.goto(`/app/bounties/${bounty.id}`)
    await expect(requester.getByText('Status: Completed').first()).toBeVisible({ timeout: 30_000 })
  })

  await contributor.context().close()
})

test('V2-4. disputes: two of three arbiters approve a split, and it executes on-chain', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(720_000)
  const requester = page
  const title = `E2E arbiter bounty ${uniqueSuffix()}`
  const requesterWallet = await installTestWallet(requester)
  await signIn(requester, REQUESTER)
  const config = await escrowConfig(requester)
  const arbiters = arbiterKeypairs().filter((k) => config.arbiter_addresses.includes(k.publicKey()))
  test.skip(
    config.contract_version < 2 || config.arbiter_threshold !== 2 || config.arbiter_addresses.length !== 3,
    'Needs the v2 contract with a 2-of-3 arbiter set (STELLAR_ARBITER_ADDRESSES, STELLAR_ARBITER_THRESHOLD=2).',
  )
  test.skip(arbiters.length < 2, 'E2E_ARBITER_SECRETS must hold two of the configured arbiters’ secret keys.')

  await linkWalletViaApi(requester, requesterWallet)
  const bounty = await fundedBountyViaApi(requester, requesterWallet, { title, reward_amount: '2' })
  const { page: contributor, wallet } = await newSession(browser, testInfo, guard, 'contributor')
  await registerViaApi(contributor, newUser('arb'))
  await linkWalletViaApi(contributor, wallet!)
  const application = await applyViaApi(contributor, bounty.id)
  const accepted = await acceptViaApi(requester, application.id)
  await assignOnchainViaApi(requester, bounty.id, accepted.assignment_id!, requesterWallet)
  // The split is paid against the delivered submission, so it shows as the contributor's payment.
  await submitWorkViaApi(
    contributor,
    bounty.id,
    'The first half of the scope, delivered before the project paused.',
  )
  const dispute = await apiCall<{ id: string }>(contributor, 'POST', `/bounties/${bounty.id}/disputes`, {
    reason: 'Half of the scope was delivered before the requester paused the project.',
  })
  await chainActionViaApi(
    contributor,
    bounty.id,
    { action: 'RAISE_DISPUTE', dispute_id: dispute.id },
    wallet!,
  )

  // Each arbiter is a staff account that verified its own arbiter wallet.
  const { page: moderator, wallet: first } = await sessionWithKeypair(
    browser,
    testInfo,
    guard,
    'moderator',
    arbiters[0],
  )
  await signIn(moderator, MODERATOR)
  await ensureWalletLinked(moderator, first)
  const { page: admin, wallet: second } = await sessionWithKeypair(
    browser,
    testInfo,
    guard,
    'admin',
    arbiters[1],
  )
  await signIn(admin, ADMIN)
  await ensureWalletLinked(admin, second)

  await test.step('a moderator records a split: 1.5 XLM to the contributor, 0.5 XLM back', async () => {
    await moderator.goto('/admin/disputes')
    const row = moderator.getByRole('row').filter({ hasText: title })
    await expect(row.getByText('Escrow frozen')).toBeVisible()
    await row.getByRole('button', { name: /resolve the dispute/i }).click()
    const dialog = moderator.getByRole('dialog', { name: 'Resolve dispute' })
    await dialog.getByRole('combobox', { name: 'Decision' }).click()
    await moderator.getByRole('option', { name: 'Split the reward' }).click()
    await expect(dialog.getByText(/open reward is 2\./)).toBeVisible()
    await dialog.getByLabel('Contributor receives').fill('1.5')
    await dialog.getByLabel('Decision note').fill('Half of the scope shipped; split the reward accordingly.')
    await dialog.getByRole('button', { name: 'Record decision' }).click()
    await expect(dialog).toBeHidden()
    const notice = moderator.getByRole('status').filter({ hasText: 'Decision recorded' })
    await expect(notice.getByText(/2 arbiter wallets must now approve/i)).toBeVisible()
    await expect(row.getByText('0 of 2 approvals')).toBeVisible()
  })

  await test.step('the first arbiter approves: 1 of 2, no funds move yet', async () => {
    const row = moderator.getByRole('row').filter({ hasText: title })
    await row.getByRole('button', { name: 'Sign as arbiter' }).click()
    const dialog = moderator.getByRole('dialog', { name: /approve dispute decision/i })
    await expect(dialog.getByText('0 of 2 approvals')).toBeVisible({ timeout: 30_000 })
    await expect(dialog.getByText(/1\.5 to the contributor, 0\.5 back to the requester/)).toBeVisible()
    await signChainDialog(moderator, /approve dispute decision/i)
    await moderator.reload()
    await expect(
      moderator.getByRole('row').filter({ hasText: title }).getByText('1 of 2 approvals'),
    ).toBeVisible({
      timeout: 30_000,
    })
    await contributor.goto(`/bounties/${bounty.slug}`)
    const panel = contributor.getByRole('region', { name: 'Dispute' })
    await expect(panel.getByText('Waiting for the arbiters')).toBeVisible()
    await expect(panel.getByRole('progressbar', { name: 'Arbiter approvals' })).toHaveAttribute(
      'aria-valuenow',
      '1',
    )
  })

  await test.step('the second arbiter approves the same split and the escrow pays out', async () => {
    await admin.goto('/admin/disputes')
    const row = admin.getByRole('row').filter({ hasText: title })
    await row.getByRole('button', { name: 'Sign as arbiter' }).click()
    const dialog = admin.getByRole('dialog', { name: /approve dispute decision/i })
    await expect(dialog.getByText('1 of 2 approvals')).toBeVisible({ timeout: 30_000 })
    await signChainDialog(admin, /approve dispute decision/i)
    await admin.reload()
    await expect(admin.getByRole('row').filter({ hasText: title }).getByText('Closed')).toBeVisible({
      timeout: 30_000,
    })

    await contributor.goto('/app/payments')
    const received = contributor.getByRole('row').filter({ hasText: title })
    await expect(received.getByText('Confirmed')).toBeVisible({ timeout: 30_000 })
    await expect(received.getByText('1.5')).toBeVisible()
    await contributor.goto(`/bounties/${bounty.slug}`)
    await expect(
      contributor.getByRole('region', { name: 'Dispute' }).getByText('Split the reward'),
    ).toBeVisible()
  })

  await contributor.context().close()
  await moderator.context().close()
  await admin.context().close()
})
