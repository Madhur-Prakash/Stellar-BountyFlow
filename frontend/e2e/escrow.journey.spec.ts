import { apiCall, expect, newUser, registerViaApi, signIn, test, uniqueSuffix } from './fixtures'
import { ADMIN, REQUESTER } from './support/accounts'
import { EXPLORER_TX, signChainDialog } from './support/chain-ui'
import { acceptViaApi, applyViaApi, fundedBountyViaApi, linkWalletViaApi, newSession } from './support/flows'
import { installTestWallet } from './support/wallet'

/**
 * Journeys 11 and 12 on Stellar Testnet: cancellation + refund, and the
 * dispute flow (off-chain decision; the arbiter's on-chain execution is
 * presented but not signed, because the arbiter key never leaves its owner).
 */

test('11. cancel a funded bounty: request cancellation → on-chain request → refund', async ({ page }) => {
  test.setTimeout(420_000)
  const wallet = await installTestWallet(page)
  await signIn(page, REQUESTER)
  await linkWalletViaApi(page, wallet)
  const bounty = await fundedBountyViaApi(page, wallet, { title: `E2E refund bounty ${uniqueSuffix()}` })

  await page.goto(`/app/bounties/${bounty.id}`)
  await expect(page.getByText('Status: Funded').first()).toBeVisible()

  await page.getByRole('button', { name: 'Cancel bounty' }).click()
  const dialog = page.getByRole('dialog', { name: /cancel this bounty/i })
  await expect(dialog.getByText(/the bounty is funded, so this requests cancellation/i)).toBeVisible()
  await dialog.getByLabel('Reason').fill('nope')
  await dialog.getByRole('button', { name: 'Cancel bounty' }).click()
  await expect(dialog.getByText('Write at least 5 characters.')).toBeVisible()
  await dialog.getByLabel('Reason').fill('Scope moved to another team.')
  await dialog.getByRole('button', { name: 'Cancel bounty' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Status: Cancel requested').first()).toBeVisible()
  await expect(page.getByText(/first request cancellation on-chain, then refund the escrow/i)).toBeVisible()
  // Refunding straight away is not offered while the escrow is still "Funded".
  await expect(page.getByRole('button', { name: 'Refund escrow' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Request cancellation on-chain' }).click()
  await signChainDialog(page, /request cancellation/i)
  const escrow = page.locator('[data-slot="card"]').filter({ hasText: 'In escrow' })
  await expect(escrow.getByText('Cancellation requested')).toBeVisible({ timeout: 30_000 })

  await page.getByRole('button', { name: 'Refund escrow' }).click()
  await signChainDialog(page, /refund escrow/i)

  await expect(page.getByText('Status: Cancelled').first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Funding: Refunded').first()).toBeVisible()
  await expect(escrow.getByText('Refunded', { exact: true })).toBeVisible()
  const txs = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Transactions' }) })
  await expect(txs.getByRole('row').filter({ hasText: 'Cancel requested' })).toHaveCount(1)
  const refund = txs.getByRole('row').filter({ hasText: /^Refund/ })
  await expect(refund.getByText('Confirmed')).toBeVisible()
  await expect(refund.getByRole('link', { name: /view on explorer/i })).toHaveAttribute('href', EXPLORER_TX)
  await expect(page.getByRole('button', { name: 'Cancel bounty' })).toHaveCount(0)
})

test('12. dispute: assign on-chain, contributor raises and freezes the escrow, a moderator decides, the arbiter step is presented', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(600_000)
  const requester = page
  const title = `E2E dispute bounty ${uniqueSuffix()}`

  // Setup (not under test): a funded bounty with an accepted contributor who has a verified wallet.
  const requesterWallet = await installTestWallet(requester)
  await signIn(requester, REQUESTER)
  await linkWalletViaApi(requester, requesterWallet)
  const bounty = await fundedBountyViaApi(requester, requesterWallet, { title })
  const { page: contributor, wallet: contributorWallet } = await newSession(
    browser,
    testInfo,
    guard,
    'contributor',
  )
  const contributorUser = await registerViaApi(contributor, newUser('contrib'))
  await linkWalletViaApi(contributor, contributorWallet!)
  const application = await applyViaApi(contributor, bounty.id)
  await acceptViaApi(requester, application.id)

  await test.step('requester records the assignment on-chain', async () => {
    await requester.goto(`/app/bounties/${bounty.id}/applications`)
    await requester.getByRole('tab', { name: 'Accepted' }).click()
    const card = requester.getByRole('listitem').filter({ hasText: contributorUser.displayName })
    await card.getByRole('button', { name: 'Record assignment on-chain' }).click()
    await signChainDialog(requester, /assign contributor/i)
    await expect(card.getByText('Assigned on-chain')).toBeVisible({ timeout: 30_000 })
    await expect(card.getByRole('button', { name: 'Record assignment on-chain' })).toHaveCount(0)
  })

  await test.step('contributor raises a dispute and freezes the escrow on-chain', async () => {
    await contributor.goto(`/bounties/${bounty.slug}`)
    const panel = contributor.getByRole('region', { name: 'Dispute' })
    await panel.getByRole('button', { name: 'Raise a dispute' }).click()
    const dialog = contributor.getByRole('dialog', { name: 'Raise a dispute' })
    await dialog.getByLabel('What went wrong?').fill('Too short')
    await dialog.getByRole('button', { name: 'Raise dispute' }).click()
    await expect(dialog.getByText('Write at least 20 characters.')).toBeVisible()
    await dialog
      .getByLabel('What went wrong?')
      .fill('The requester changed the scope after I started and will not review the delivered work.')
    await dialog.getByLabel(/evidence link/i).fill('https://github.com/stellar/js-stellar-sdk/issues/1')
    await dialog.getByRole('button', { name: 'Raise dispute' }).click()
    await expect(dialog).toBeHidden()
    await expect(contributor.getByText('Status: Disputed').first()).toBeVisible()
    await expect(panel.getByText('Open', { exact: true })).toBeVisible()

    await panel.getByRole('button', { name: 'Freeze escrow on-chain' }).click()
    await signChainDialog(contributor, /freeze escrow/i)
    await expect(panel.getByText('Escrow frozen')).toBeVisible({ timeout: 30_000 })
    await expect(contributor.getByText('Funding: Disputed, escrow locked').first()).toBeVisible()
  })

  const { page: admin } = await newSession(browser, testInfo, guard, 'admin')
  await test.step('admin assigns and resolves the dispute; the arbiter signature step is presented', async () => {
    await signIn(admin, ADMIN)
    await admin.goto('/admin/disputes')
    const row = admin.getByRole('row').filter({ hasText: title })
    await expect(row.getByText('Escrow frozen')).toBeVisible()
    await row.getByRole('button', { name: /assign the dispute/i }).click()
    await expect(row.getByText('Under review')).toBeVisible()
    await row.getByRole('button', { name: /resolve the dispute/i }).click()

    const dialog = admin.getByRole('dialog', { name: 'Resolve dispute' })
    await expect(dialog.getByRole('combobox', { name: 'Decision' })).toHaveText(/release to contributor/i)
    await dialog.getByLabel('Decision note').fill('Too short')
    await dialog.getByRole('button', { name: 'Record decision' }).click()
    await expect(dialog.getByText('Write at least 10 characters.')).toBeVisible()
    await dialog
      .getByLabel('Decision note')
      .fill('The delivered work meets the published acceptance criteria.')
    await dialog.getByRole('button', { name: 'Record decision' }).click()
    await expect(dialog).toBeHidden()

    const notice = admin.getByRole('status').filter({ hasText: 'Decision recorded' })
    await expect(notice.getByText(/arbiter wallet must now sign/i)).toBeVisible()
    await expect(row.getByText('Awaiting arbiter signature')).toBeVisible()

    // The RESOLVE_DISPUTE step names the escrow's arbiter wallet; any other wallet is rejected by the contract.
    const config = await apiCall<{ arbiter_address: string }>(admin, 'GET', '/config/public')
    await notice.getByRole('button', { name: 'Sign as arbiter' }).click()
    const chain = admin.getByRole('dialog', { name: /execute dispute decision/i })
    await expect(chain.getByText(/arbiter wallet must sign this transaction/i)).toBeVisible()
    await expect(
      chain.getByText(`${config.arbiter_address.slice(0, 4)}…${config.arbiter_address.slice(-4)}`),
    ).toBeVisible()
    await chain
      .getByRole('button', { name: 'Close' })
      .or(chain.getByRole('button', { name: 'Cancel' }))
      .first()
      .click()
    await expect(chain).toBeHidden()
  })

  await test.step('both parties see the recorded decision while the arbiter step is pending', async () => {
    await contributor.goto(`/bounties/${bounty.slug}`)
    const panel = contributor.getByRole('region', { name: 'Dispute' })
    await expect(panel.getByText('Release the reward to the contributor')).toBeVisible()
    await expect(panel.getByText('Waiting for the arbiter')).toBeVisible()
    await expect(contributor.getByText('Status: Disputed').first()).toBeVisible()
  })

  await contributor.context().close()
  await admin.context().close()
})

test('12b. dispute resolved off-chain (escrow not frozen) returns the bounty to work', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(420_000)
  const title = `E2E off-chain dispute ${uniqueSuffix()}`
  const requesterWallet = await installTestWallet(page)
  await signIn(page, REQUESTER)
  await linkWalletViaApi(page, requesterWallet)
  const bounty = await fundedBountyViaApi(page, requesterWallet, { title })
  const { page: contributor, wallet } = await newSession(browser, testInfo, guard, 'contributor')
  await registerViaApi(contributor, newUser('contrib'))
  await linkWalletViaApi(contributor, wallet!)
  const application = await applyViaApi(contributor, bounty.id)
  await acceptViaApi(page, application.id)

  // The requester raises the dispute from the management page; the contributor is not assigned on-chain.
  await page.goto(`/app/bounties/${bounty.id}`)
  const panel = page.getByRole('region', { name: 'Dispute' })
  await panel.getByRole('button', { name: 'Raise a dispute' }).click()
  const dialog = page.getByRole('dialog', { name: 'Raise a dispute' })
  await dialog
    .getByLabel('What went wrong?')
    .fill('The contributor has not started the work two weeks after being accepted.')
  await dialog.getByRole('button', { name: 'Raise dispute' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Status: Disputed').first()).toBeVisible()
  await expect(panel.getByText(/not assigned on-chain, so the escrow itself can’t be frozen/)).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Freeze escrow on-chain' })).toHaveCount(0)

  const { page: admin } = await newSession(browser, testInfo, guard, 'admin', { wallet: false })
  await signIn(admin, ADMIN)
  await admin.goto('/admin/disputes')
  const row = admin.getByRole('row').filter({ hasText: title })
  await row.getByRole('button', { name: /resolve the dispute/i }).click()
  const resolve = admin.getByRole('dialog', { name: 'Resolve dispute' })
  await resolve.getByRole('combobox', { name: 'Decision' }).click()
  await admin.getByRole('option', { name: 'Refund to requester' }).click()
  await resolve
    .getByLabel('Decision note')
    .fill('No work was delivered; the requester may refund the escrow.')
  await resolve.getByRole('button', { name: 'Record decision' }).click()
  await expect(resolve).toBeHidden()
  const notice = admin.getByRole('status').filter({ hasText: 'Decision recorded' })
  await expect(
    notice.getByText(/not frozen on-chain, so the decision is applied in BountyFlow/i),
  ).toBeVisible()
  await expect(notice.getByRole('button', { name: 'Sign as arbiter' })).toHaveCount(0)
  await expect(row.getByText('Closed')).toBeVisible()

  await page.reload()
  await expect(page.getByText('Status: Disputed')).toHaveCount(0)
  await expect(panel.getByText('Refund the requester')).toBeVisible()

  await contributor.context().close()
  await admin.context().close()
})
