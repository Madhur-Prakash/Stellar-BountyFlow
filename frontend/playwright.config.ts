import { defineConfig, devices } from '@playwright/test'

/**
 * End-to-end suite. It drives the real frontend against a running BountyFlow
 * API on Stellar Testnet — see docs/testing.md for how to start the isolated
 * E2E stack. Playwright cannot drive the Freighter extension, so the dev
 * server runs with VITE_ENABLE_TEST_WALLET=true and each session gets a
 * Friendbot-funded keypair that signs in the test process (e2e/support/wallet.ts). By default it targets http://localhost:5174; override with
 * E2E_BASE_URL (PW_BASE_URL is still honoured for backwards compatibility).
 * Set PW_WEB_SERVER=1 to let Playwright start `pnpm dev` itself.
 *
 * Projects:
 * - desktop-chromium (1280×800) runs everything, including the heavy
 *   journey specs (`*.journey.spec.ts`).
 * - tablet (768×1024) and mobile (Pixel 7) run the public, responsive and
 *   accessibility specs.
 * - motion (1280×800) runs `motion.spec.ts` with animations on: smooth
 *   scrolling, the reward pool, the draggable rail, pinned scrolling and skeletons.
 * Every other project runs as a reduced-motion user, so GSAP entrances and
 * smooth scrolling are off and assertions see final, fully visible content.
 */
const baseURL = process.env.E2E_BASE_URL ?? process.env.PW_BASE_URL ?? 'http://localhost:5174'

const JOURNEYS = /.*\.journey\.spec\.ts$/
const MOTION = /.*motion\.spec\.ts$/

export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.E2E_WORKERS ? Number(process.env.E2E_WORKERS) : process.env.CI ? 2 : 4,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  globalSetup: './e2e/global-setup.ts',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    // Light is the product's default theme.
    colorScheme: 'light',
    reducedMotion: 'reduce',
  },
  projects: [
    {
      name: 'desktop-chromium',
      testIgnore: MOTION,
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'tablet',
      testIgnore: [JOURNEYS, MOTION],
      use: { ...devices['Desktop Chrome'], viewport: { width: 768, height: 1024 }, hasTouch: true },
    },
    {
      name: 'mobile',
      testIgnore: [JOURNEYS, MOTION],
      use: { ...devices['Pixel 7'] },
    },
    {
      name: 'motion',
      testMatch: MOTION,
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1280, height: 800 },
        reducedMotion: 'no-preference',
      },
    },
  ],
  webServer: process.env.PW_WEB_SERVER
    ? {
        command: 'pnpm dev --port 5174 --strictPort',
        url: baseURL,
        reuseExistingServer: true,
        timeout: 120_000,
      }
    : undefined,
})
