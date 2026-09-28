import { expect, test } from '@playwright/test'

test.describe('public pages', () => {
  test('landing renders hero and primary navigation', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('reward held in escrow')
    await expect(page.getByRole('main').getByRole('link', { name: 'Browse bounties' }).first()).toBeVisible()
    await expect(page.getByRole('banner')).toBeVisible()
  })

  test('marketplace page renders search and filters', async ({ page }) => {
    await page.goto('/bounties')
    await expect(page.getByRole('heading', { level: 1, name: /bounty marketplace/i })).toBeVisible()
    await expect(page.getByRole('searchbox', { name: /search bounties/i })).toBeVisible()
  })

  test('mobile menu opens at 375px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 })
    await page.goto('/')
    await page.getByRole('button', { name: /open menu/i }).click()
    const dialog = page.getByRole('dialog', { name: 'Menu' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('link', { name: 'Marketplace' })).toBeVisible()
  })

  test('unknown routes show the not-found page', async ({ page }) => {
    await page.goto('/definitely-not-a-page')
    await expect(page.getByRole('heading', { name: /page not found/i })).toBeVisible()
  })
})
