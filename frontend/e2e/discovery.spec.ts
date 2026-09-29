import { ADMIN, CONTRIBUTOR, REQUESTER } from './support/accounts'
import { createBountyViaApi } from './support/flows'
import {
  apiCall,
  expect,
  MAILPIT_URL,
  signIn,
  signInViaApi,
  test,
  uniqueSuffix,
  waitForAppIdle,
} from './fixtures'

/**
 * Discovery: saved searches with alerts, and skill-graph recommendations.
 *
 * The contributor saves a marketplace search with filters, the seeded requester publishes a matching bounty, and
 * the alert arrives both in the app and in Mailpit. The digest is then driven through the admin trigger, which
 * only exists when DISCOVERY_DIGEST_TRIGGER_ENABLED is set. No money moves here, so nothing touches Testnet.
 */

type SavedSearch = { id: string; name: string; new_count: number; alert_frequency: string }
type Bounty = { id: string; slug: string; title: string }

const SKILL = 'soroban'

/** Mailpit search, newest first. */
async function mailFor(
  request: { get: (url: string) => Promise<{ ok(): boolean; json(): Promise<unknown> }> },
  to: string,
  subject: RegExp,
) {
  const res = await request.get(
    `${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}&limit=50`,
  )
  if (!res.ok()) return []
  const body = (await res.json()) as { messages?: { ID: string; Subject: string }[] }
  return (body.messages ?? []).filter((m) => subject.test(m.Subject))
}

test.describe('discovery', () => {
  test('a saved search alerts in the app and by email when a matching bounty is published', async ({
    page,
    browser,
    request,
  }) => {
    const suffix = uniqueSuffix()
    const marker = `escrow indexer ${suffix}`

    // The contributor saves the marketplace search they are following.
    await signIn(page, CONTRIBUTOR)
    await page.goto(`/bounties?q=${encodeURIComponent(marker)}&skills=${SKILL}`)
    await waitForAppIdle(page)
    await page.getByRole('button', { name: 'Save search' }).click()

    const dialog = page.getByRole('dialog', { name: /save this search/i })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByLabel('Name')).toHaveValue(marker)
    await expect(dialog.getByLabel('Alerts')).toContainText('Instant')
    await dialog.getByRole('button', { name: 'Save search' }).click()
    await expect(dialog).toBeHidden()

    const saved = await apiCall<SavedSearch[]>(page, 'GET', '/saved-searches')
    const search = saved.find((s) => s.name === marker)
    expect(search, 'the saved search was created').toBeTruthy()

    // The seeded requester publishes a bounty that matches it, in their own browser session.
    const requesterContext = await browser.newContext({ baseURL: page.url() })
    const requesterPage = await requesterContext.newPage()
    try {
      await signInViaApi(requesterPage, REQUESTER)
      const bounty = await createBountyViaApi(requesterPage, {
        title: `Build an ${marker}`,
        short_description: 'Index Soroban escrow contract events into Postgres for the payouts dashboard.',
        required_skills: [SKILL, 'rust'],
        tags: ['backend'],
      })
      await apiCall(requesterPage, 'POST', `/bounties/${bounty.id}/publish`)

      // The worker matches it against saved searches and raises the alert.
      await expect
        .poll(
          async () => {
            const list = await apiCall<SavedSearch[]>(page, 'GET', '/saved-searches')
            return list.find((s) => s.id === search!.id)?.new_count ?? 0
          },
          { message: 'the saved search counts the new match', timeout: 60_000, intervals: [1000, 2000] },
        )
        .toBeGreaterThan(0)

      await page.goto('/app/notifications')
      await waitForAppIdle(page)
      const notification = page.getByText(new RegExp(`matches your saved search`, 'i')).first()
      await expect(notification).toBeVisible()
      await expect(page.getByText(new RegExp(marker, 'i')).first()).toBeVisible()

      // The same alert arrives as an email carrying an unsubscribe link.
      await expect
        .poll(
          async () => (await mailFor(request, CONTRIBUTOR.email, /new bounty for your saved search/i)).length,
          {
            message: 'the alert email reaches Mailpit',
            timeout: 90_000,
            intervals: [1000, 2000],
          },
        )
        .toBeGreaterThan(0)

      const [message] = await mailFor(request, CONTRIBUTOR.email, /new bounty for your saved search/i)
      const detail = await request.get(`${MAILPIT_URL}/api/v1/message/${message!.ID}`)
      const body = (await detail.json()) as { Text?: string; HTML?: string }
      const text = `${body.Text ?? ''}\n${body.HTML ?? ''}`.replaceAll('&amp;', '&')
      expect(text).toContain(marker)
      expect(text).toMatch(/\/saved-searches\/unsubscribe\?token=/)

      // The saved search opens back in the marketplace, and looking at it clears the new count.
      await page.goto('/app/saved?tab=searches')
      await waitForAppIdle(page)
      await expect(page.getByRole('heading', { name: marker })).toBeVisible()
      await page.getByRole('link', { name: 'Open in marketplace' }).first().click()
      await expect(page).toHaveURL(/\/bounties\?/)
      await expect(page.getByRole('region', { name: 'Saved search' })).toContainText(marker)
      await expect
        .poll(async () => {
          const list = await apiCall<SavedSearch[]>(page, 'GET', '/saved-searches')
          return list.find((s) => s.id === search!.id)?.new_count ?? -1
        })
        .toBe(0)
    } finally {
      await requesterContext.close()
    }
  })

  test('the digest job collects matches for a daily saved search', async ({ page, browser, request }) => {
    const suffix = uniqueSuffix()
    const marker = `digest topic ${suffix}`

    await signIn(page, CONTRIBUTOR)
    const search = await apiCall<SavedSearch>(page, 'POST', '/saved-searches', {
      name: marker,
      filters: { q: marker },
      alert_frequency: 'DAILY',
    })
    expect(search.alert_frequency).toBe('DAILY')

    const requesterContext = await browser.newContext({ baseURL: page.url() })
    const requesterPage = await requesterContext.newPage()
    try {
      await signInViaApi(requesterPage, REQUESTER)
      const bounty = await createBountyViaApi(requesterPage, {
        title: `Write the ${marker} guide`,
        short_description: `A practical guide covering the ${marker} end to end, with runnable samples.`,
      })
      await apiCall(requesterPage, 'POST', `/bounties/${bounty.id}/publish`)
      await expect
        .poll(
          async () => {
            const list = await apiCall<SavedSearch[]>(page, 'GET', '/saved-searches')
            return list.find((s) => s.id === search.id)?.new_count ?? 0
          },
          { message: 'the bounty matched the daily search', timeout: 60_000, intervals: [1000, 2000] },
        )
        .toBeGreaterThan(0)

      // Nothing is emailed before the digest runs.
      expect(await mailFor(request, CONTRIBUTOR.email, /daily bounty digest/i)).toHaveLength(0)

      // The admin trigger exists only when DISCOVERY_DIGEST_TRIGGER_ENABLED is set; skip the rest when it is off.
      const adminContext = await browser.newContext({ baseURL: page.url() })
      const adminPage = await adminContext.newPage()
      try {
        await signInViaApi(adminPage, ADMIN)
        const cookie = (await adminContext.cookies()).find((c) => c.name === 'bf_csrf')
        const run = await adminPage.request.fetch('/api/v1/admin/discovery/digests/run', {
          method: 'POST',
          data: { frequency: 'DAILY' },
          headers: cookie ? { 'X-CSRF-Token': cookie.value } : {},
        })
        test.skip(run.status() === 404, 'DISCOVERY_DIGEST_TRIGGER_ENABLED is off on this stack')
        expect(run.ok(), `digest run: ${await run.text()}`).toBe(true)
        const result = (await run.json()) as { matches: number }
        expect(result.matches).toBeGreaterThan(0)
      } finally {
        await adminContext.close()
      }

      await expect
        .poll(async () => (await mailFor(request, CONTRIBUTOR.email, /daily bounty digest/i)).length, {
          message: 'the digest email reaches Mailpit',
          timeout: 90_000,
          intervals: [1000, 2000],
        })
        .toBeGreaterThan(0)

      const [digest] = await mailFor(request, CONTRIBUTOR.email, /daily bounty digest/i)
      const detail = await request.get(`${MAILPIT_URL}/api/v1/message/${digest!.ID}`)
      const body = (await detail.json()) as { Text?: string; HTML?: string }
      expect(`${body.Text ?? ''}\n${body.HTML ?? ''}`).toContain(marker)
    } finally {
      await requesterContext.close()
    }
  })

  test('recommendations rank open bounties by the contributor’s skills', async ({ page }) => {
    await signIn(page, CONTRIBUTOR)

    // The seeded contributor has profile skills, so the ranking has seeds to start from.
    const me = await apiCall<{ skills: string[] }>(page, 'GET', '/users/me')
    expect(me.skills.length, 'the seeded contributor has profile skills').toBeGreaterThan(0)

    const recommendations = await apiCall<{
      items: {
        bounty: Bounty
        reason: { matched_skills: string[]; related_skills: { skill: string; via: string }[] }
      }[]
      seed_skills: string[]
      has_profile_skills: boolean
    }>(page, 'GET', '/recommendations')
    expect(recommendations.has_profile_skills).toBe(true)
    expect(recommendations.seed_skills.length).toBeGreaterThan(0)

    // Every recommendation explains itself with the skills it matched.
    for (const item of recommendations.items) {
      const { matched_skills: matched, related_skills: related } = item.reason
      expect(matched.length + related.length, `${item.bounty.title} has a reason`).toBeGreaterThan(0)
    }

    // "For you" on the marketplace shows the same ranking with its reason under each result.
    await page.goto('/bounties?sort=for_you')
    await waitForAppIdle(page)
    await expect(page.getByRole('heading', { level: 1, name: /bounty marketplace/i })).toBeVisible()
    if (recommendations.items.length > 0) {
      await expect(page.getByRole('list', { name: 'Recommended bounties' })).toBeVisible()
      await expect(page.getByText(/^(Matches|Related to) /).first()).toBeVisible()
    } else {
      await expect(page.getByText(/nothing matches your skills right now/i)).toBeVisible()
    }

    // The dashboard widget carries the same reasons.
    await page.goto('/app')
    await waitForAppIdle(page)
    await expect(page.getByRole('region', { name: 'Recommended for you' })).toBeVisible()
  })
})
