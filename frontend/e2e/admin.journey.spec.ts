import { API, apiCall, expect, newUser, registerViaApi, signIn, signInViaApi, test, toast, uniqueSuffix } from './fixtures'
import { ADMIN, CONTRIBUTOR, REQUESTER } from './support/accounts'
import { createBountyViaApi, newSession } from './support/flows'

/** Journey 14: staff console RBAC, user management and bounty moderation. */

test('normal users cannot reach the admin console', async ({ page }) => {
  await signIn(page, CONTRIBUTOR)
  await page.goto('/app')
  await expect(page.getByRole('link', { name: 'Admin console' })).toHaveCount(0)
  await page.goto('/admin/users')
  await expect(page.getByRole('heading', { name: 'You don’t have access to this area' })).toBeVisible()
  await expect(page.getByRole('table')).toHaveCount(0)
  // The API enforces the same rule.
  const res = await page.request.get(`${API}/admin/users`)
  expect(res.status()).toBe(403)
})

test('anonymous visitors are sent to login from /admin', async ({ page }) => {
  await page.goto('/admin')
  await expect(page).toHaveURL(/\/login\?next=%2Fadmin/)
})

test('admin sees every console section with data', async ({ page }) => {
  await signIn(page, ADMIN)
  await page.goto('/app')
  await page.getByRole('link', { name: 'Admin console' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Admin overview' })).toBeVisible()

  const sections = ['Users', 'Bounties', 'Reports', 'Disputes', 'Transactions', 'Audit logs']
  const nav = page.locator('[data-sidebar="sidebar"]')
  for (const name of sections) {
    await nav.getByRole('link', { name, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/admin/${name.toLowerCase().replace(' ', '-')}$`))
    await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
    // Either data rows (table on desktop) or a clear empty state — never a spinner or an error.
    await expect(
      page.getByRole('main').locator('tbody tr').first().or(page.getByRole('main').getByText(/^No /).first()),
    ).toBeVisible()
    await expect(page.getByRole('main').getByText(/could not load/i)).toHaveCount(0)
  }
  // Seeded users are always present.
  await nav.getByRole('link', { name: 'Users', exact: true }).click()
  await page.getByRole('searchbox', { name: 'Search users' }).fill(REQUESTER.username)
  await expect(page.getByRole('main').getByText(REQUESTER.email).first()).toBeVisible()
})

test('admin changes a role and suspends a throwaway account', async ({ page, browser, guard }, testInfo) => {
  test.setTimeout(120_000)
  const { page: other } = await newSession(browser, testInfo, guard, 'throwaway', { wallet: false })
  const user = await registerViaApi(other, newUser('sus'))

  await signIn(page, ADMIN)
  await page.goto('/admin/users')
  await page.getByRole('searchbox', { name: 'Search users' }).fill(user.username)
  const row = page.getByRole('row').filter({ hasText: user.username })
  await expect(row).toHaveCount(1)

  await row.getByRole('combobox', { name: `Role for @${user.username}` }).click()
  await page.getByRole('option', { name: 'Moderator' }).click()
  await toast(page, `Role for @${user.username} changed to Moderator.`)
  await row.getByRole('combobox', { name: `Role for @${user.username}` }).click()
  await page.getByRole('option', { name: 'User' }).click()
  await toast(page, `Role for @${user.username} changed to User.`)

  await row.getByRole('button', { name: `Suspend @${user.username}` }).click()
  const confirm = page.getByRole('alertdialog', { name: `Suspend @${user.username}?` })
  await confirm.getByRole('button', { name: 'Suspend account' }).click()
  await expect(confirm).toBeHidden()
  await expect(row.getByText('Suspended')).toBeVisible()

  // The suspended account is signed out everywhere.
  const me = await other.request.get(`${API}/auth/me`)
  expect(me.status()).toBeGreaterThanOrEqual(401)
  await other.context().close()
})

test('admin hides and unhides a bounty (only the relevant action is offered)', async ({ page, browser, guard }, testInfo) => {
  const { page: requester } = await newSession(browser, testInfo, guard, 'requester', { wallet: false })
  // This session only makes API calls, so it signs in through the API.
  await signInViaApi(requester, REQUESTER)
  const title = `E2E moderation bounty ${uniqueSuffix()}`
  const bounty = await createBountyViaApi(requester, { title })
  await apiCall(requester, 'POST', `/bounties/${bounty.id}/publish`)
  await requester.context().close()

  await signIn(page, ADMIN)
  await page.goto('/admin/bounties')
  await page.getByRole('searchbox', { name: 'Search bounties' }).fill(title)
  const row = page.getByRole('row').filter({ hasText: title })
  await expect(row).toHaveCount(1)

  await row.getByRole('button', { name: `Moderation actions for ${title}` }).click()
  await expect(page.getByRole('menuitem', { name: 'Unhide' })).toHaveCount(0)
  await page.getByRole('menuitem', { name: 'Hide from marketplace' }).click()
  const hide = page.getByRole('dialog', { name: 'Hide bounty' })
  await hide.getByLabel('Reason').fill('Duplicate listing')
  await hide.getByRole('button', { name: 'Hide bounty' }).click()
  await expect(hide).toBeHidden()
  await expect(row.getByText('Hidden')).toBeVisible()

  await row.getByRole('button', { name: `Moderation actions for ${title}` }).click()
  await expect(page.getByRole('menuitem', { name: 'Hide from marketplace' })).toHaveCount(0)
  await page.getByRole('menuitem', { name: 'Unhide' }).click()
  const unhide = page.getByRole('dialog', { name: 'Unhide bounty' })
  await unhide.getByLabel('Reason').fill('Reviewed, listing is fine')
  await unhide.getByRole('button', { name: 'Unhide bounty' }).click()
  await expect(unhide).toBeHidden()
  await expect(row.getByText('Hidden')).toHaveCount(0)
})
