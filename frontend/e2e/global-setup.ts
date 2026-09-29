import { request, type FullConfig } from '@playwright/test'

import { REQUESTER } from './support/accounts'
import { E2E_REDIS_URL, resetRateLimits } from './support/redis'

/**
 * Fails fast with a readable message when the E2E stack is not running or the
 * seeded accounts cannot sign in, and resets rate-limit counters so
 * back-to-back runs do not hit 429s.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL ?? 'http://localhost:5174'
  const ctx = await request.newContext({ baseURL })
  try {
    const health = await ctx.get('/health', { timeout: 15_000 }).catch(() => null)
    if (!health?.ok()) {
      throw new Error(
        `The BountyFlow E2E stack is not reachable at ${baseURL} (GET /health failed). ` +
          'Start the API, worker and Vite dev server first — see docs/testing.md → "End-to-end (Playwright)".',
      )
    }
    const cfg = await ctx.get('/api/v1/config/public')
    const body = (await cfg.json()) as { blockchain_mode?: string; contract_id?: string }
    if (body.blockchain_mode !== 'testnet' || !body.contract_id) {
      throw new Error(
        `The E2E suite runs against Stellar Testnet and needs BLOCKCHAIN_MODE=testnet and a configured ` +
          `SOROBAN_CONTRACT_ID (got mode=${body.blockchain_mode}, contract=${body.contract_id ?? 'none'}). ` +
          'See docs/testing.md.',
      )
    }
    // The specs sign in as the seeded accounts with email + password.
    await resetRateLimits()
    const login = await ctx.post('/api/v1/auth/login', { data: { email: REQUESTER.email, password: REQUESTER.password } })
    if (!login.ok()) {
      throw new Error(
        `The seeded account ${REQUESTER.email} could not sign in (HTTP ${login.status()}). The API must run the ` +
          'development seed, and E2E_SEED_PASSWORD must match the backend SEED_USER_PASSWORD (default "BountyFlow!2026").',
      )
    }
    // That sign-in counted against the login limits, so clearing must find those counters. If it finds none, the
    // harness is looking at a different Redis database than the API, and the suite would hit 429s part way through.
    const cleared = await resetRateLimits()
    if (cleared === 0) {
      throw new Error(
        `E2E_REDIS_URL (${E2E_REDIS_URL}) is not the Redis database the API uses: no rate-limit counters were found ` +
          'after a sign-in. Set E2E_REDIS_URL to the API’s REDIS_URL (for the docker compose stack, ' +
          'redis://localhost:6379/0). See docs/testing.md.',
      )
    }
    // The dev server must enable the test wallet provider (VITE_ENABLE_TEST_WALLET=true), or signing would stall.
    const walletModule = await ctx.get('/src/lib/stellar/wallet.ts')
    if (walletModule.ok() && !(await walletModule.text()).includes('"VITE_ENABLE_TEST_WALLET": "true"')) {
      throw new Error(
        'The Vite dev server was started without VITE_ENABLE_TEST_WALLET=true, so the E2E test wallet cannot sign. ' +
          'Restart it with VITE_ENABLE_TEST_WALLET=true (development mode only; see docs/testing.md).',
      )
    }
  } finally {
    await ctx.dispose()
  }
  await resetRateLimits()
}
