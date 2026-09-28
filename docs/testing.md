# Testing

| Suite | Command | Needs | What it covers |
|---|---|---|---|
| Backend unit | `make test-api-unit` | nothing | Money, RBAC matrix, state machine, event schemas, retry/backoff/DLQ decisions, notification mapping, email rendering, preferences, analytics rules, outbox relay |
| Backend integration | `make test-api-integration` | Postgres (`bountyflow_test`) | Full API through httpx: auth/CSRF/refresh rotation, verification and reset emails, profiles, wallets (real SEP-10 signatures), bounty CRUD and search, the complete funded lifecycle, concurrent-accept race, cancel/refund, disputes, RBAC, notifications, admin, analytics |
| Security regression | part of `make test-api` | Postgres | CSRF coverage across all mutating routes, IDOR matrix, signature rules (only real signatures are accepted) (see [security.md](security.md)) |
| Testnet E2E (opt-in) | `make test-testnet` | Running API in testnet mode, Friendbot | Real Stellar Testnet: fund escrow → apply → accept → submit → revise → approve → payout → verify, plus duplicate-payout rejection |
| Contract | `make contract-test` | Rust | 36 Soroban unit tests: auth, funding, payouts, duplicate prevention, refunds, deadlines, disputes, events |
| Frontend unit | `make test-frontend` | Node | Vitest + Testing Library: forms, API client (CSRF, refresh single-flight), money helpers, badges, guards, safe markdown |
| End-to-end | `make test-e2e` | Running stack | Playwright scenarios across desktop, tablet and mobile viewports (see below) |

## Isolation

- Integration tests use **`TEST_DATABASE_URL`**, an isolated database created by `infra/postgres/init`. The
  fixture refuses to run against the development database. The schema is created once per session and every
  table is truncated after each test.
- Redis is replaced with **fakeredis**. Email goes to a capturing backend. Kafka is replaced by the in-process
  dispatcher (the same handlers and idempotency tables).
- Chain actions use a **test double** (`tests/support/fake_chain.py`). It builds real transaction XDR, the tests
  sign it with real keypairs, and the backend's real signature verification runs; the calls then execute against
  an in-memory model of the escrow contract. The application itself has no simulated mode. The opt-in
  `make test-testnet` suite and the Playwright suite exercise the real Stellar Testnet.

## End-to-end scenarios

Playwright drives the real frontend against the real API on **Stellar Testnet**. A test-only wallet provider,
compiled in only when `VITE_ENABLE_TEST_WALLET=true` in development builds, signs with Friendbot-funded keypairs
held in the Playwright process:

1. Register a user (the verification email is read from Mailpit's API) and complete onboarding.
2. Create and publish a bounty, then fund it.
3. Discover it as another user and apply.
4. Accept the application.
5. Submit work, request a revision, resubmit.
6. Approve and pay out, then view the transaction record.
7. Check responsive layouts at 375 px, 768 px and 1280 px, keyboard navigation and focus visibility.

### Running the Playwright suite (`pnpm test:e2e`)

The suite needs an isolated stack: its own database, its own Redis index, an API + worker in Testnet mode, and
a Vite dev server with the test wallet enabled. Infra (Postgres, Redis, Mailpit) comes from `make infra`.

1. **Database.** Create (or reset) `bountyflow_test_e2e`. The API migrates and seeds it on start:

   ```bash
   docker compose exec -T postgres psql -U bountyflow -d postgres \
     -c "DROP DATABASE IF EXISTS bountyflow_test_e2e WITH (FORCE);" -c "CREATE DATABASE bountyflow_test_e2e;"
   ```

2. **API and worker** (two terminals, from `backend/`). These variables override the root `.env`; the contract,
   native-asset contract and arbiter settings still come from `.env`:

   ```bash
   export DATABASE_URL=postgresql+psycopg://bountyflow:<password>@localhost:5432/bountyflow_test_e2e
   export REDIS_URL=redis://localhost:6379/5
   export BLOCKCHAIN_MODE=testnet STELLAR_NETWORK=testnet KAFKA_ENABLED=false
   export API_PORT=8013 FRONTEND_URL=http://localhost:5174 CORS_ORIGINS=http://localhost:5174
   export RUN_MIGRATIONS_ON_STARTUP=true SEED_ON_STARTUP=true
   uv run python -m app.serve       # terminal 1
   uv run python -m worker.main     # terminal 2 (dispatches outbox events in-process: notifications + emails)
   ```

3. **Frontend** (from `frontend/`):

   ```bash
   VITE_API_PROXY_TARGET=http://localhost:8013 VITE_ENABLE_TEST_WALLET=true pnpm dev --port 5174 --strictPort
   ```

   `VITE_ENABLE_TEST_WALLET=true` is a development-only flag. It lets the app use a wallet object that
   Playwright injects (`window.__BOUNTYFLOW_TEST_WALLET__`) instead of the Freighter extension, which Playwright
   cannot drive. The page only sees the public key: every signature is produced in the Playwright process
   (`e2e/support/wallet.ts`, via `page.exposeFunction`) with a fresh keypair per session, funded by Friendbot.
   `vite build` in production mode refuses to run with the flag set.

4. **Run it:**

   ```bash
   E2E_BASE_URL=http://localhost:5174 pnpm test:e2e                            # all projects
   E2E_BASE_URL=http://localhost:5174 pnpm test:e2e --project=desktop-chromium # journeys + desktop checks only
   E2E_SCREENSHOTS=1 pnpm test:e2e screenshots --project=desktop-chromium     # design screenshots → e2e/screenshots/
   E2E_README_SHOTS=1 pnpm test:e2e readme-screenshots --project=desktop-chromium # README images → docs/screenshots/
   ```

   Take the README images against a freshly seeded database (for example a new database for the API in step 2
   with `RUN_MIGRATIONS_ON_STARTUP=true SEED_ON_STARTUP=true`), so they show the seeded marketplace and nothing
   left over from earlier test runs. The spec creates no bounties; it links a wallet to the seeded requester and
   prepares, without signing, a funding transaction for one of her bounties.

| Variable | Default | Purpose |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost:5174` | Frontend under test (`PW_BASE_URL` is still honoured) |
| `E2E_MAILPIT_URL` | `http://localhost:8025` | Mailpit HTTP API used to read verification and reset emails |
| `E2E_REDIS_URL` | `redis://localhost:6379/5` | The E2E Redis index; the harness clears only `bf:v1:rl:*` rate-limit counters so repeated runs do not hit 429s. Never point it at a shared index. |
| `E2E_FRIENDBOT_URL` / `E2E_HORIZON_URL` | Testnet defaults | Account funding and the "account exists" check |
| `E2E_SEED_PASSWORD` | `BountyFlow!2026` | Password of the seeded accounts; must match the backend `SEED_USER_PASSWORD` |
| `E2E_WORKERS` | `4` (`2` in CI) | Playwright workers |
| `PW_WEB_SERVER` | unset | `1` lets Playwright start the dev server itself |

Projects: `desktop-chromium` (1280×800) runs everything, including the `*.journey.spec.ts` flows; `tablet`
(768×1024) and `mobile` (Pixel 7) run the public, responsive and accessibility specs. These three run as a
reduced-motion user, so GSAP entrances and smooth scrolling are off and assertions see final content. The
`motion` project (1280×800, motion on) runs `e2e/motion.spec.ts`, which covers:

- ScrollSmoother on the landing page and Lenis on the marketplace
- the reward pool: tokens rise onto the floor, drag without opening, and click through to their bounty
- the draggable rail and its buttons
- the pinned story advancing with scroll, and the escrow vault drawing
- captured skeletons showing while results load
- the reduced-motion fallback

Every test fails on uncaught page errors, `console.error` output and any 5xx API response (`e2e/fixtures.ts`).
Traces and screenshots are kept for failures under `frontend/test-results/`.

Run the journeys against the isolated E2E stack above, not the development database: they create real bounties,
accounts and Testnet transactions.

Notes:

- Journeys sign in through the login form as seeded accounts (Ada as requester, Morgan as admin, Priya as
  moderator), plus a freshly registered contributor per test: a payout
  goes to the contributor's most recently verified wallet, so sharing one contributor account across parallel
  tests would race.
- On-chain confirmations are real, so journeys allow up to 90 s per transaction. The dispute journey records
  the moderator's decision and checks the arbiter signing step. It does not sign `RESOLVE_DISPUTE`, because the
  arbiter key stays with its owner.
- The worker delivers emails one at a time. If SMTP to Mailpit is slow on your machine (about 8 s per message
  under Docker Desktop, caused by Mailpit's reverse-DNS lookup of the client), set `MP_SMTP_DISABLE_RDNS=true`
  on the Mailpit container. The suite waits up to 90 s for an email.

## CI

`.github/workflows/ci.yml` runs:

- backend lint (ruff), types (mypy), migration up/check/down and tests with coverage;
- frontend lint, typecheck, unit tests and build, plus a forbidden-icon check;
- contract fmt, clippy, tests and the wasm build;
- the Playwright E2E suite against the API on Stellar Testnet.
