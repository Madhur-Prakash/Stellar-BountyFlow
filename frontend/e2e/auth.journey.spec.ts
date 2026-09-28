import { expect, newUser, readEmailLink, registerViaApi, signIn, test, toast } from './fixtures'
import { CONTRIBUTOR, REQUESTER } from './support/accounts'
import { resetRateLimits } from './support/redis'
import { installTestWallet, verifyWalletViaUi } from './support/wallet'

/** Journeys 1 and 13: registration, verification, onboarding and auth edge cases. */

test('1. register → verify email from Mailpit → complete the onboarding checklist', async ({ page }) => {
  test.setTimeout(240_000)
  const user = newUser('reg')
  const wallet = await installTestWallet(page)
  await resetRateLimits()

  await test.step('register through the form (with client-side validation first)', async () => {
    await page.goto('/register')
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page.getByText('Enter your email address.')).toBeVisible()
    await expect(page.getByText('You need to accept the terms to continue.')).toBeVisible()

    await page.getByLabel('Email').fill(user.email)
    await page.getByLabel('Username').fill(user.username)
    await page.getByLabel('Display name').fill(user.displayName)
    await page.getByLabel('Password', { exact: true }).fill(user.password)
    await page.getByLabel('Confirm password').fill(`${user.password}x`)
    await page.getByRole('checkbox').check()
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page.getByText('Passwords don’t match.')).toBeVisible()
    await page.getByLabel('Confirm password').fill(user.password)
    await page.getByRole('button', { name: 'Create account' }).click()

    await expect(page).toHaveURL(/\/app\/onboarding/)
    await expect(page.getByRole('heading', { level: 1, name: 'Set up your account' })).toBeVisible()
    await expect(page.getByRole('alert').filter({ hasText: /verify your email/i })).toBeVisible()
  })

  await test.step('open the verification link from the email', async () => {
    const { url } = await readEmailLink(page.request, user.email, /confirm your email/i, '/verify-email')
    await page.goto(url)
    await expect(page.getByRole('heading', { name: 'Email verified' })).toBeVisible()
    await page.getByRole('link', { name: 'Continue to dashboard' }).click()
    await expect(page).toHaveURL(/\/app/)
  })

  await test.step('complete profile, role and wallet steps', async () => {
    await page.goto('/app/onboarding')
    const progress = page.getByRole('list', { name: 'Onboarding progress' })
    await expect(progress.getByText('Verify your email (done)')).toBeAttached()

    await page.getByLabel('Post bounties and pay for work').check()
    await page.getByLabel('Find work and earn rewards').check()
    await page.getByLabel('Short bio').fill('QA engineer who writes end-to-end journeys for escrow marketplaces.')
    await page.getByLabel('Skills').fill('playwright, typescript, qa')
    await page.getByRole('button', { name: 'Save profile' }).click()
    await toast(page, 'Profile saved')
    await expect(progress.getByText('Choose how you’ll use BountyFlow (done)')).toBeAttached()
    await expect(progress.getByText('Add a bio and skills (done)')).toBeAttached()

    // Real Testnet wallet (Friendbot-funded, signing in the test process): prove ownership through the UI.
    await verifyWalletViaUi(page, wallet)
    await expect(progress.getByText('Link a wallet (done)')).toBeAttached()

    await page.getByRole('button', { name: 'Finish onboarding' }).click()
    await expect(page).toHaveURL(/\/app$/)
  })

  await test.step('the verified wallet is listed on the profile', async () => {
    await page.goto('/app/profile')
    const card = page.locator('[data-slot="card"]').filter({ hasText: 'Linked wallets' })
    await expect(card.getByText('Ownership verified by signature')).toBeVisible()
    await expect(card.getByRole('link', { name: /view wallet address on stellar explorer/i })).toHaveAttribute(
      'href',
      `https://stellar.expert/explorer/testnet/account/${wallet.publicKey}`,
    )
  })
})

test.describe('13. auth edge cases', () => {
  test('wrong password shows an error and keeps the user on /login', async ({ page }) => {
    await resetRateLimits()
    await page.goto('/login')
    await page.getByLabel('Email').fill(REQUESTER.email)
    await page.getByLabel('Password', { exact: true }).fill('definitely-not-the-password')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: /invalid|incorrect|wrong/i })).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('forgot password → reset via the Mailpit link → sign in with the new password', async ({ page }) => {
    test.setTimeout(240_000)
    const user = await registerViaApi(page)
    await page.context().clearCookies()
    const newPassword = `${user.password}-new`

    await page.goto('/login')
    await page.getByRole('link', { name: 'Forgot password?' }).click()
    await expect(page).toHaveURL(/\/forgot-password/)
    await expect(page.getByRole('heading', { level: 1, name: 'Reset your password' })).toBeVisible()
    await page.getByLabel('Email').fill(user.email)
    await page.getByRole('button', { name: /send reset link/i }).click()
    await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible()

    const { url } = await readEmailLink(page.request, user.email, /reset your/i, '/reset-password')
    await page.goto(url)
    await expect(page.getByRole('heading', { name: 'Choose a new password' })).toBeVisible()
    await page.getByLabel('New password', { exact: true }).fill('short')
    await page.getByRole('button', { name: /update password|reset password|save/i }).click()
    await expect(page.getByText(/at least 10 characters/i).first()).toBeVisible()
    await page.getByLabel('New password', { exact: true }).fill(newPassword)
    await page.getByLabel('Confirm new password').fill(newPassword)
    await page.getByRole('button', { name: /update password|reset password|save/i }).click()
    await expect(page).toHaveURL(/\/login/)
    await toast(page, /password updated/i)

    // The old password no longer works; the new one does.
    await resetRateLimits()
    await page.getByLabel('Email').fill(user.email)
    await page.getByLabel('Password', { exact: true }).fill(user.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: /invalid|incorrect|wrong/i })).toBeVisible()
    await page.getByLabel('Password', { exact: true }).fill(newPassword)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/app\/onboarding/)
  })

  test('protected routes redirect to /login?next=… and return there after login', async ({ page }) => {
    await page.goto('/app/payments?tab=sent')
    await expect(page).toHaveURL(/\/login\?next=%2Fapp%2Fpayments%3Ftab%3Dsent/)
    await expect(page.getByText('Sign in to continue where you left off.')).toBeVisible()
    await resetRateLimits()
    await page.getByLabel('Email').fill(CONTRIBUTOR.email)
    await page.getByLabel('Password', { exact: true }).fill(CONTRIBUTOR.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page).toHaveURL(/\/app\/payments\?tab=sent$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Payments' })).toBeVisible()
  })

  test('a seeded account signs in with email and password; logout clears the session', async ({ page }) => {
    await signIn(page, CONTRIBUTOR)
    await expect(page).toHaveURL(/\/app$/)
    await page.getByRole('button', { name: 'Account menu' }).click()
    const menu = page.getByRole('menu')
    await expect(menu.getByText(CONTRIBUTOR.displayName, { exact: true })).toBeVisible()
    await expect(menu.getByText(`@${CONTRIBUTOR.username}`, { exact: true })).toBeVisible()
    await menu.getByRole('menuitem', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('banner').getByRole('link', { name: /sign in/i }).first()).toBeVisible()
    await page.goto('/app')
    await expect(page).toHaveURL(/\/login\?next=%2Fapp/)
  })

  test('signed-in users are bounced away from /login', async ({ page }) => {
    await signIn(page, REQUESTER)
    await page.goto('/login')
    await expect(page).toHaveURL(/\/app$/)
  })
})
