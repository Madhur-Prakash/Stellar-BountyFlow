import { expect, newUser, registerViaApi, signIn, test, toast, uniqueSuffix } from './fixtures'
import { REQUESTER } from './support/accounts'
import { EXPLORER_TX, signChainDialog } from './support/chain-ui'
import { newSession } from './support/flows'
import { installTestWallet, verifyWalletViaUi } from './support/wallet'

/**
 * Journeys 2–10: the complete funded bounty lifecycle on Stellar Testnet,
 * driven through the UI by two separate users (the seeded requester and a
 * freshly registered contributor), each with a fresh Friendbot-funded wallet.
 * Contributors are per-test accounts: a payout goes to the contributor's most
 * recently verified wallet, so sharing one account across parallel tests
 * would race.
 */
test.describe('bounty lifecycle', () => {
  test.describe.configure({ mode: 'serial' })

  test('create → fund → discover → apply → accept → submit → revise → approve → pay out', async ({
    page,
    browser,
    guard,
  }, testInfo) => {
    test.setTimeout(600_000)
    const s = uniqueSuffix()
    const title = `E2E lifecycle bounty ${s}`
    const requester = page
    let bountyUrl = ''

    const requesterWallet = await installTestWallet(requester)

    await test.step('2a. requester signs in, verifies a wallet, and sees validation errors for bad input', async () => {
      await signIn(requester, REQUESTER)
      await verifyWalletViaUi(requester, requesterWallet)
      await requester.goto('/app/bounties/create')
      await expect(requester.getByRole('heading', { level: 1, name: 'Post a bounty' })).toBeVisible()
      await requester.getByRole('button', { name: 'Save draft' }).click()
      await expect(requester.getByText('Use at least 8 characters.')).toBeVisible()
      await expect(requester.getByText('Describe the work in at least 50 characters.')).toBeVisible()
      await expect(requester.getByText('Enter a positive XLM amount with up to 7 decimals.')).toBeVisible()
      await expect(requester).toHaveURL(/\/app\/bounties\/create$/)

      await requester.getByLabel('Reward per position (XLM)').fill('12.123456789')
      await requester.getByLabel('Positions', { exact: true }).fill('0')
      await requester.getByLabel('Positions', { exact: true }).blur()
      await expect(requester.getByText('Between 1 and 100 positions.')).toBeVisible()
    })

    await test.step('2b. create the draft with valid input', async () => {
      await requester.getByLabel('Title', { exact: true }).fill(title)
      await requester.getByLabel('Summary').fill('Write an end-to-end test report for the BountyFlow lifecycle journey.')
      await requester
        .getByLabel('Full description')
        .fill('## Scope\n\nDocument every step of the lifecycle journey, including screenshots and the transaction hashes.')
      await requester.getByLabel('Reward per position (XLM)').fill('2.5')
      await requester.getByLabel('Positions', { exact: true }).fill('1')
      await expect(requester.getByText('2.5 XLM', { exact: true })).toBeVisible()
      await requester.getByLabel('Required skills').fill('playwright, qa')
      await requester.getByLabel('Acceptance criteria').fill('- Every journey step is covered\n- Report linked')
      await requester.getByRole('button', { name: 'Save draft' }).click()
      await expect(requester).toHaveURL(/\/app\/bounties\/[0-9a-f-]{36}$/)
      await expect(requester.getByRole('heading', { level: 1, name: title })).toBeVisible()
      await expect(requester.getByText('Status: Draft').first()).toBeVisible()
      bountyUrl = requester.url()
    })

    await test.step('2c. publish and fund the escrow on Testnet through the chain dialog', async () => {
      await requester.getByRole('button', { name: 'Publish' }).click()
      await expect(requester.getByText('Status: Open').first()).toBeVisible()

      await requester.getByRole('button', { name: 'Fund escrow' }).click()
      const dialog = requester.getByRole('dialog', { name: /fund escrow/i })
      await expect(dialog.getByText('2.5 XLM', { exact: true })).toBeVisible({ timeout: 60_000 })
      await signChainDialog(requester, /fund escrow/i)

      await expect(requester.getByText('Status: Funded').first()).toBeVisible({ timeout: 30_000 })
      await expect(requester.getByText('Funding: Funded in escrow').first()).toBeVisible()
      const escrow = requester.locator('[data-slot="card"]').filter({ hasText: 'In escrow' })
      await expect(escrow.getByText('Holding funds')).toBeVisible()
      await expect(escrow.getByText('100%')).toBeVisible()
      await expect(escrow.getByRole('link', { name: /verify escrow on explorer/i })).toHaveAttribute(
        'href',
        /^https:\/\/stellar\.expert\/explorer\/testnet\/contract\/C[A-Z0-9]{55}$/,
      )

      const txSection = requester.locator('section').filter({ has: requester.getByRole('heading', { name: 'Transactions' }) })
      const row = txSection.getByRole('row').filter({ hasText: 'Escrow created' })
      await expect(row.getByText('Confirmed')).toBeVisible()
      await expect(row.getByRole('link', { name: /view on explorer/i })).toHaveAttribute('href', EXPLORER_TX)
    })

    const { page: contributor, wallet: contributorWallet } = await newSession(browser, testInfo, guard, 'contributor')

    const contributorUser = newUser('contrib')
    await test.step('3. contributor verifies a wallet, discovers the bounty with search, filters and sort, then applies', async () => {
      await registerViaApi(contributor, contributorUser)
      await contributor.goto('/app')
      await verifyWalletViaUi(contributor, contributorWallet!)
      await contributor.goto('/bounties')
      await contributor.getByRole('searchbox', { name: /search bounties/i }).fill(s)
      await expect(contributor).toHaveURL(new RegExp(`q=${s}`))
      await expect(contributor.getByRole('heading', { name: /1 bounty for/ })).toBeVisible()

      const filters = contributor.getByRole('complementary', { name: 'Bounty filters' })
      await filters.getByRole('switch', { name: /funded only/i }).click()
      await expect(contributor).toHaveURL(/funded_only=true/)
      await contributor.getByRole('combobox', { name: /sort bounties/i }).click()
      await contributor.getByRole('option', { name: 'Reward: high to low' }).click()
      await expect(contributor).toHaveURL(/sort=reward_high/)

      const card = contributor.getByRole('article').filter({ hasText: title })
      await expect(card).toHaveCount(1)
      await expect(card.getByText('Funding: Funded in escrow')).toBeVisible()
      await card.getByRole('link', { name: title }).click()

      await expect(contributor.getByRole('heading', { level: 1, name: title })).toBeVisible()
      await contributor.getByRole('button', { name: 'Apply', exact: true }).click()
      const dialog = contributor.getByRole('dialog', { name: /apply to this bounty/i })
      await dialog.getByLabel('Proposal').fill('Short')
      await dialog.getByRole('button', { name: 'Send application' }).click()
      await expect(dialog.getByText(/at least 30 characters/)).toBeVisible()
      await dialog
        .getByLabel('Proposal')
        .fill('I will cover every lifecycle step with screenshots and link the on-chain transactions.')
      await dialog.getByLabel('Portfolio links (optional)').fill('https://github.com/stellar')
      await dialog.getByRole('button', { name: 'Send application' }).click()
      await expect(dialog).toBeHidden()
      await toast(contributor, /application sent/i)
      await expect(contributor.getByText('Your application:')).toContainText('Pending')
    })

    await test.step('4. requester reviews the application and accepts it', async () => {
      await requester.goto(`${bountyUrl}/applications`)
      const card = requester.getByRole('listitem').filter({ hasText: contributorUser.displayName })
      await expect(card).toBeVisible()
      await expect(card.getByText('I will cover every lifecycle step')).toBeVisible()
      await card.getByRole('button', { name: 'Accept' }).click()
      const dialog = requester.getByRole('dialog', { name: `Accept ${contributorUser.displayName}?` })
      await dialog.getByLabel(/note to the contributor/i).fill('Welcome aboard!')
      await dialog.getByRole('button', { name: 'Accept' }).click()
      await expect(dialog).toBeHidden()
      await toast(requester, /applicant accepted/i)
      await requester.getByRole('tab', { name: 'Accepted' }).click()
      await expect(requester.getByRole('listitem').filter({ hasText: contributorUser.displayName }).getByText('Accepted')).toBeVisible()
    })

    await test.step('5. contributor submits work', async () => {
      await contributor.reload()
      await expect(contributor.getByText('You’re assigned to this bounty.')).toBeVisible()
      await contributor.getByRole('button', { name: 'Submit work' }).click()
      const dialog = contributor.getByRole('dialog', { name: /submit your work/i })
      await dialog.getByLabel('What you delivered').fill('Too short')
      await dialog.getByRole('button', { name: 'Submit work' }).click()
      await expect(dialog.getByText(/at least 20 characters/)).toBeVisible()
      await dialog.getByLabel('What you delivered').fill('First version of the lifecycle report, covering funding and applications.')
      await dialog.getByLabel(/primary evidence link/i).fill('https://github.com/stellar/js-stellar-sdk/pull/1')
      await dialog.getByRole('button', { name: 'Submit work' }).click()
      await expect(dialog).toBeHidden()
      await toast(contributor, /work submitted/i)
      await expect(contributor.getByText('Status: Under review').first()).toBeVisible()
    })

    await test.step('6. requester requests a revision', async () => {
      await requester.goto(`${bountyUrl}/submissions`)
      const card = requester.getByRole('listitem').filter({ hasText: 'First version of the lifecycle report' })
      await expect(card.getByText('Submitted', { exact: true })).toBeVisible()
      await card.getByRole('button', { name: 'Request revision' }).click()
      const dialog = requester.getByRole('dialog', { name: /request a revision/i })
      await dialog.getByLabel(/what needs to change/i).fill('Please add the payout section as well.')
      await dialog.getByRole('button', { name: 'Request revision' }).click()
      await expect(dialog).toBeHidden()
      await expect(card.getByText('Revision requested', { exact: true })).toBeVisible()
    })

    await test.step('7. contributor resubmits from My submissions', async () => {
      await contributor.goto('/app/submissions')
      const row = contributor.getByRole('row').filter({ hasText: title })
      await expect(row.getByText('Revision requested')).toBeVisible()
      await expect(row.getByText('Please add the payout section as well.')).toBeVisible()
      await row.getByRole('button', { name: 'Send revision' }).click()
      const dialog = contributor.getByRole('dialog', { name: /send a revised version/i })
      await expect(dialog.getByText('Please add the payout section as well.')).toBeVisible()
      await dialog
        .getByLabel('What you delivered')
        .fill('Second version: covers funding, applications, reviews and the payout from escrow.')
      await dialog.getByRole('button', { name: 'Send revision' }).click()
      await expect(dialog).toBeHidden()
      await expect(row.getByText('Resubmitted')).toBeVisible()
      await expect(row.getByText('v2')).toBeVisible()
    })

    await test.step('8. requester approves', async () => {
      await requester.reload()
      const card = requester.getByRole('listitem').filter({ hasText: 'Second version' })
      await expect(card.getByText('Resubmitted', { exact: true })).toBeVisible()
      await card.getByRole('button', { name: 'Approve' }).click()
      const dialog = requester.getByRole('dialog', { name: /approve this submission/i })
      await dialog.getByRole('button', { name: 'Approve' }).click()
      await expect(dialog).toBeHidden()
      await expect(card.getByText('Approved', { exact: true })).toBeVisible()
      await expect(card.getByText('Awaiting payout')).toBeVisible()
    })

    await test.step('9. requester pays out on Testnet through the chain dialog', async () => {
      const card = requester.getByRole('listitem').filter({ hasText: 'Second version' })
      await card.getByRole('button', { name: 'Pay 2.5 XLM' }).click()
      await expect(requester.getByRole('dialog', { name: /release payout/i }).getByText('2.5 XLM', { exact: true })).toBeVisible({
        timeout: 60_000,
      })
      await signChainDialog(requester, /release payout/i)
      await expect(card.getByText('Confirmed', { exact: true }).first()).toBeVisible({ timeout: 30_000 })

      await requester.goto(bountyUrl)
      await expect(requester.getByText('Status: Completed').first()).toBeVisible({ timeout: 30_000 })

      await requester.goto('/app/transactions')
      const payout = requester.getByRole('row').filter({ hasText: title }).filter({ hasText: 'Payout' })
      await expect(payout).toHaveCount(1)
      await expect(payout.getByText('2.5')).toBeVisible()
      await expect(payout.getByText('Confirmed')).toBeVisible()
      await expect(payout.getByRole('link', { name: /view on explorer/i })).toHaveAttribute('href', EXPLORER_TX)

      await contributor.goto('/app/payments')
      const received = contributor.getByRole('row').filter({ hasText: title })
      await expect(received.getByText('Confirmed')).toBeVisible()
      await expect(received.getByText('2.5')).toBeVisible()
      await expect(received.getByRole('link', { name: title })).toHaveAttribute('href', /\/bounties\//)
    })

    await test.step('10. contributor notifications: unread bell, list, mark all read', async () => {
      await contributor.goto('/app/notifications')
      const bell = contributor.getByRole('link', { name: /notifications, \d+ unread/i })
      await expect(async () => {
        await contributor.reload()
        await expect(bell).toBeVisible({ timeout: 2_000 })
        const list = contributor.getByRole('list').filter({ hasText: title })
        for (const type of ['Application accepted', 'Revision requested', 'Submission approved', 'Payment confirmed']) {
          await expect(list.getByText(type, { exact: true }).first()).toBeVisible({ timeout: 2_000 })
        }
      }).toPass({ timeout: 60_000 })

      await contributor.getByRole('button', { name: 'Mark all read' }).click()
      await toast(contributor, /marked as read/i)
      await expect(contributor.getByText('0 unread')).toBeVisible()
      await expect(contributor.getByRole('link', { name: /notifications, \d+ unread/i })).toHaveCount(0)
    })

    await contributor.context().close()
  })
})
