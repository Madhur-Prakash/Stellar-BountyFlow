import { apiCall, expect, newUser, registerViaApi, signIn, test, uniqueSuffix, waitForAppIdle } from './fixtures'
import { CONTRIBUTOR, MODERATOR, REQUESTER } from './support/accounts'
import { signChainDialog } from './support/chain-ui'
import {
  acceptViaApi,
  applyViaApi,
  createBountyViaApi,
  fundedBountyViaApi,
  linkWalletViaApi,
  newSession,
} from './support/flows'
import {
  FOREIGN_PR_URL,
  GITHUB_LOGIN,
  gistUrl,
  MERGED_PR_URL,
  OPEN_PR_URL,
  registerFixtureGist,
  REPO_URL,
} from './support/github-fixtures'
import { installTestWallet } from './support/wallet'

/**
 * Collaboration: threaded Q&A on a bounty, and GitHub account linking plus pull request verification.
 *
 * GitHub itself is never called: the API runs with `GITHUB_FIXTURE_TRANSPORT=true` (test mode only) and replays
 * responses recorded from real public pull requests in `stellar/js-stellar-sdk`, so no test depends on a real
 * person's gist or on GitHub being reachable. The Stellar side is real Testnet, as everywhere else.
 */

const DESKTOP_ONLY = 'chain-funded journey: desktop project only'

test('Q&A: a question, the requester’s answer, accepting it, a reply, a report and a moderator hiding it', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.setTimeout(180_000)
  const title = `E2E questions bounty ${uniqueSuffix()}`

  // Setup (not under test): a published bounty owned by the seeded requester.
  await signIn(page, REQUESTER)
  const bounty = await createBountyViaApi(page, { title })
  await apiCall(page, 'POST', `/bounties/${bounty.id}/publish`)

  const { page: asker } = await newSession(browser, testInfo, guard, 'asker', { wallet: false })
  await signIn(asker, CONTRIBUTOR)

  await test.step('anyone signed in can ask, and the question shows on the bounty', async () => {
    await asker.goto(`/bounties/${bounty.slug}`)
    await waitForAppIdle(asker)
    const section = asker.getByRole('region', { name: 'Questions' })
    await expect(section.getByText('No questions yet')).toBeVisible()
    await section.getByRole('button', { name: 'Ask a question' }).click()
    const box = section.getByLabel('Your question')
    await box.fill('Too short')
    await section.getByRole('button', { name: 'Post question' }).click()
    await expect(section.getByText('Write at least 10 characters.')).toBeVisible()
    await box.fill('Does the **deliverable** need a demo video, or is a written walkthrough enough?')
    await section.getByRole('button', { name: 'Post question' }).click()
    // Markdown is rendered, not shown raw.
    await expect(section.getByRole('strong').filter({ hasText: 'deliverable' })).toBeVisible()
    await expect(section.getByRole('heading', { name: /^Questions \(1\)$/ })).toBeVisible()
  })

  await test.step('the requester answers, and the answer is marked as theirs', async () => {
    await page.goto(`/bounties/${bounty.slug}`)
    await waitForAppIdle(page)
    const section = page.getByRole('region', { name: 'Questions' })
    await section.getByRole('button', { name: 'Reply' }).click()
    await section.getByLabel('Your reply').fill('A written walkthrough is enough. Screenshots help.')
    await section.getByRole('button', { name: 'Post reply' }).click()
    const reply = section.getByRole('listitem').filter({ hasText: 'A written walkthrough is enough' })
    await expect(reply.getByText('Requester')).toBeVisible()
  })

  await test.step('the requester accepts the answer and pins the question', async () => {
    const section = page.getByRole('region', { name: 'Questions' })
    const reply = section.getByRole('listitem').filter({ hasText: 'A written walkthrough is enough' })
    await reply.getByRole('button', { name: 'Accept' }).click()
    await expect(reply.getByText('Accepted answer')).toBeVisible()
    await section.getByRole('button', { name: 'Pin', exact: true }).first().click()
    await expect(section.getByText('Pinned').first()).toBeVisible()
  })

  await test.step('another contributor replies in the same thread', async () => {
    const { page: other } = await newSession(browser, testInfo, guard, 'replier', { wallet: false })
    await registerViaApi(other, newUser('qa'))
    // A new account must verify its email before posting; the seeded accounts already have.
    await other.goto(`/bounties/${bounty.slug}`)
    await waitForAppIdle(other)
    await expect(
      other.getByRole('region', { name: 'Questions' }).getByText('Verify your email', { exact: false }),
    ).toBeHidden()
    await other.close()

    await asker.reload()
    await waitForAppIdle(asker)
    const section = asker.getByRole('region', { name: 'Questions' })
    await section.getByRole('button', { name: 'Reply' }).click()
    await section.getByLabel('Your reply').fill('Thanks — I will include the walkthrough in the README.')
    await section.getByRole('button', { name: 'Post reply' }).click()
    await expect(section.getByText('I will include the walkthrough')).toBeVisible()
  })

  await test.step('the asker edits their question, which is marked as edited', async () => {
    const section = asker.getByRole('region', { name: 'Questions' })
    const question = section.getByRole('listitem').filter({ hasText: 'Does the' }).first()
    await question.getByRole('button', { name: 'Edit' }).first().click()
    await question
      .getByRole('textbox')
      .fill('Does the deliverable need a demo video, or is a written walkthrough enough? (updated)')
    await question.getByRole('button', { name: 'Save' }).click()
    await expect(question.getByText('edited')).toBeVisible()
  })

  await test.step('the requester’s answer is reported', async () => {
    const section = asker.getByRole('region', { name: 'Questions' })
    const reply = section.getByRole('listitem').filter({ hasText: 'A written walkthrough is enough' })
    await reply.getByRole('button', { name: 'Report' }).click()
    const dialog = asker.getByRole('dialog', { name: 'Report this reply' })
    await dialog.getByLabel('What’s wrong?').fill('Testing the moderation queue end to end.')
    await dialog.getByRole('button', { name: 'Send report' }).click()
    await expect(dialog).toBeHidden()
  })

  await test.step('a moderator sees the report with its context and hides the post', async () => {
    const { page: moderator } = await newSession(browser, testInfo, guard, 'moderator', { wallet: false })
    await signIn(moderator, MODERATOR)
    await moderator.goto('/admin/reports')
    await waitForAppIdle(moderator)
    const row = moderator.getByRole('row').filter({ hasText: 'A written walkthrough is enough' })
    await expect(row.getByText('Qa post')).toBeVisible()
    await row.getByRole('button', { name: 'Hide' }).click()
    const dialog = moderator.getByRole('dialog', { name: 'Hide this post?' })
    await dialog.getByLabel('Reason').fill('Hidden by the end-to-end suite.')
    await dialog.getByRole('button', { name: 'Hide post' }).click()
    await expect(dialog).toBeHidden()
    // Hiding a post actions the open reports that pointed at it.
    await expect(row.getByText('Actioned')).toBeVisible()
    await moderator.close()
  })

  await test.step('the hidden reply is gone for readers, and the report queue says so', async () => {
    const anon = await browser.newContext({ baseURL: testInfo.project.use.baseURL })
    const visitor = await anon.newPage()
    guard.watch(visitor, 'visitor')
    await visitor.goto(`/bounties/${bounty.slug}`)
    await waitForAppIdle(visitor)
    const section = visitor.getByRole('region', { name: 'Questions' })
    await expect(section.getByText('A written walkthrough is enough')).toBeHidden()
    await expect(section.getByText('A moderator hid this post.')).toBeVisible()
    await visitor.close()
    await anon.close()
  })
})

test('GitHub: link an account with a gist, link pull requests, and the merged-PR approval gate', async ({
  page,
  browser,
  guard,
}, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-chromium', DESKTOP_ONLY)
  test.setTimeout(600_000)
  const title = `E2E pull request bounty ${uniqueSuffix()}`

  // Setup (not under test): a funded bounty that requires a merged pull request, with an accepted contributor.
  const requesterWallet = await installTestWallet(page)
  await signIn(page, REQUESTER)
  await linkWalletViaApi(page, requesterWallet)
  const bounty = await fundedBountyViaApi(page, requesterWallet, {
    title,
    repository_url: REPO_URL,
    require_merged_pr: true,
  })
  const { page: contributor, wallet: contributorWallet } = await newSession(
    browser,
    testInfo,
    guard,
    'contributor',
  )
  await signIn(contributor, CONTRIBUTOR)
  await linkWalletViaApi(contributor, contributorWallet!)
  const application = await applyViaApi(contributor, bounty.id)
  await acceptViaApi(page, application.id)

  await test.step('the contributor proves their GitHub account with a public gist', async () => {
    await contributor.goto('/app/settings#github')
    await waitForAppIdle(contributor)
    const section = contributor.getByRole('region', { name: 'GitHub' })
    await section.getByLabel('GitHub username').fill(GITHUB_LOGIN)
    await section.getByRole('button', { name: 'Continue' }).click()

    // The one-time text the user would paste into a gist; the API's test transport serves it back.
    const challenge = await section.locator('code').first().innerText()
    expect(challenge).toContain('bountyflow:')
    const gistId = `e2e${uniqueSuffix()}`.replace(/[^a-f0-9]/gi, '').slice(0, 20)
    await registerFixtureGist(gistId, `BountyFlow verification\n${challenge}\n`)

    await section.getByLabel('Paste the gist URL').fill(gistUrl(gistId))
    await section.getByRole('button', { name: 'Verify' }).click()
    await expect(section.getByText(`@${GITHUB_LOGIN}`)).toBeVisible()
    await expect(section.getByText('Verified', { exact: false }).first()).toBeVisible()
  })

  await test.step('the contributor submits work with an open pull request, which verifies', async () => {
    await contributor.goto(`/bounties/${bounty.slug}`)
    await waitForAppIdle(contributor)
    await contributor.getByRole('button', { name: 'Submit work' }).click()
    const dialog = contributor.getByRole('dialog', { name: 'Submit your work' })
    await dialog
      .getByLabel('What you delivered')
      .fill('Implemented the change; the pull request is linked for verification.')
    await dialog.getByLabel('Pull requests (optional)').fill(OPEN_PR_URL)
    await dialog.getByRole('button', { name: 'Submit work' }).click()
    await expect(dialog).toBeHidden()

    const prs = contributor.getByRole('region', { name: 'Pull requests' }).first()
    await expect(prs.getByText('stellar/js-stellar-sdk#1747')).toBeVisible()
    await expect(prs.getByText('Verified')).toBeVisible()
    await expect(prs.getByText('Open', { exact: true })).toBeVisible()
    await expect(prs.getByText('checks passed', { exact: false })).toBeVisible()
  })

  await test.step('a pull request opened by someone else is shown as an author mismatch', async () => {
    const prs = contributor.getByRole('region', { name: 'Pull requests' }).first()
    await prs.getByLabel('Link a pull request').fill(FOREIGN_PR_URL)
    await prs.getByRole('button', { name: 'Link' }).click()
    const foreign = prs.getByTestId('pull-request').filter({ hasText: '#1739' })
    await expect(foreign.getByText('Author mismatch')).toBeVisible()
    await expect(foreign.getByText(`not @${GITHUB_LOGIN}`, { exact: false })).toBeVisible()
    await foreign.getByRole('button', { name: /^Unlink/ }).click()
    await expect(foreign).toHaveCount(0)
  })

  await test.step('approval is refused while no merged pull request is verified', async () => {
    await page.goto(`/app/bounties/${bounty.id}/submissions`)
    await waitForAppIdle(page)
    const card = page.getByRole('listitem').filter({ hasText: 'stellar/js-stellar-sdk#1747' })
    await expect(card.getByText('Merged PR required')).toBeVisible()
    await card.getByRole('button', { name: 'Approve' }).click()
    const dialog = page.getByRole('dialog', { name: 'Approve this submission?' })
    await dialog.getByRole('button', { name: 'Approve' }).click()
    await expect(
      page.locator('[data-sonner-toast]').filter({ hasText: 'requires a merged pull request' }).first(),
    ).toBeVisible()
    await page.keyboard.press('Escape')
  })

  await test.step('with the merged pull request linked, the requester can approve', async () => {
    const prs = contributor.getByRole('region', { name: 'Pull requests' }).first()
    await prs.getByLabel('Link a pull request').fill(MERGED_PR_URL)
    await prs.getByRole('button', { name: 'Link' }).click()
    const merged = prs.getByTestId('pull-request').filter({ hasText: '#1744' })
    await expect(merged.getByText('Merged')).toBeVisible()
    await expect(merged.getByText('Verified')).toBeVisible()

    await page.reload()
    await waitForAppIdle(page)
    const card = page.getByRole('listitem').filter({ hasText: 'stellar/js-stellar-sdk#1744' })
    await expect(card.getByText('Merged PR verified')).toBeVisible()
    await card.getByRole('button', { name: 'Approve' }).click()
    const dialog = page.getByRole('dialog', { name: 'Approve this submission?' })
    await dialog.getByRole('button', { name: 'Approve' }).click()
    await expect(dialog).toBeHidden()
    await expect(card.getByText('Approved')).toBeVisible()
  })

  await test.step('the approved payout is released on Stellar Testnet', async () => {
    const card = page.getByRole('listitem').filter({ hasText: 'stellar/js-stellar-sdk#1744' })
    await card.getByRole('button', { name: /^Pay / }).click()
    await signChainDialog(page, /release payout|pay/i)
    await expect(card.getByText('Confirmed')).toBeVisible({ timeout: 60_000 })
  })
})
