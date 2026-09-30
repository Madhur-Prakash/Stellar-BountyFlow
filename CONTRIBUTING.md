# Contributing to BountyFlow

Thanks for helping. This guide covers the local setup, the checks every change must pass, the conventions the
codebase follows, and how to open a pull request.

> **This is a single-maintainer project**, so the honest version up front: **issues are read, pull requests are
> reviewed, and neither is on a schedule.** Small, focused changes land quickly. Large ones land only if the
> shape was agreed before the code was written — open an issue describing the change before writing it, because
> that is a much cheaper conversation than a rejected branch.
>
> There is one person behind BountyFlow, not a team or a company. "We" does not appear in these docs for that
> reason, and neither does a promised response time.

Found a vulnerability? Don't open an issue or pull request. Follow [SECURITY.md](SECURITY.md) instead.

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker (Desktop, or Engine + Compose v2) | 24+ | PostgreSQL, Redis, Kafka, Mailpit, and the full stack |
| GNU Make + bash | 4.x (Git Bash on Windows) | `make` targets |
| [uv](https://docs.astral.sh/uv/) | 0.9+ (CI pins 0.9.5) | Backend environment; installs Python 3.12 |
| Python | 3.12 (`requires-python = ">=3.12"`) | Backend |
| Node.js | 22 (`engines.node >= 22.12`) | Frontend |
| pnpm | 11 (`packageManager: pnpm@11.21.0`) | Frontend |
| Rust + `wasm32v1-none` target | stable (`contracts/README.md` lists 1.96) | Contract work only |
| Stellar CLI | 27 (CI pins 27.0.0; soroban-sdk 28 needs 25.2.0+) | Contract wasm build (`stellar contract build`) and deploy only |
| Freighter | latest, switched to Testnet | Signing transactions in the app |

## Repository layout

| Path | What lives there |
|---|---|
| `backend/app/` | FastAPI API: `core/` (config, security, RBAC, logging, middleware, rate limits), `modules/`, `blockchain/`, `messaging/`, `scripts/seed.py` |
| `backend/worker/` | Kafka consumers, outbox relay, periodic jobs |
| `backend/migrations/` | Alembic migrations |
| `backend/tests/` | `unit/`, `integration/` (including `security/`), `contract/` (opt-in Testnet run), `support/` |
| `frontend/` | React app (`src/`), Playwright suite (`e2e/`), skeleton capture script (`scripts/capture-bones.mjs`) |
| `contracts/bounty_escrow/` | Soroban escrow contract (Rust) and its unit tests |
| `contracts/deployments/` | `testnet.json`, the record of the current and superseded Testnet deployments |
| `infra/` | Postgres init (creates `bountyflow_test`) and Kafka topic bootstrap |
| `scripts/` | Contract deploy scripts (bash and PowerShell) |
| `docs/` | Architecture, API, database, blockchain, contracts, security, testing, development, deployment |
| `.github/workflows/ci.yml` | CI pipeline |

The full tree is in the README's [Repository structure](README.md#repository-structure).

## Local setup

```bash
make install   # creates .env from .env.example with a fresh JWT_SECRET (never overwrites), uv sync,
               # pnpm install, Playwright Chromium
make dev       # Postgres, Redis, Kafka (+ topics) and Mailpit in Docker; migrate + seed;
               # then API (:8000), worker and Vite (:5173) on the host. Ctrl+C stops all three.
```

To run everything in containers instead, use `make up` (app on http://localhost:5173, the same address as the
dev server). `make up-tools` adds Kafka UI, and `make down`, `make restart`, `make logs` and `make ps` manage the
stack. To run pieces separately: `make infra` — every service **except** the frontend and the backend (API,
worker, migrations), so you can run those on the host — then `make api`, `make worker` and `make frontend-dev`.

On Windows, start the API with `make api` (or `uv run python -m app.serve`), not plain uvicorn: psycopg's async
driver cannot use the default Proactor event loop.

`make help` lists every target.

### Migrations and seed data

- `make migrate` applies migrations (`alembic upgrade head`). `make migration m="describe change"` autogenerates a
  revision.
- With `RUN_MIGRATIONS_ON_STARTUP=true`, the API applies migrations on boot under a Postgres advisory lock.
- With `SEED_ON_STARTUP=true`, the API runs the seed on boot. Both are `true` in `.env.example`. The seed is
  **idempotent**: it keeps existing records and creates only missing accounts and bounties. It refuses to run in
  staging or production, and it never fabricates chain activity.
- `make seed` runs the seed by hand and prints the sign-in details. `make reset-db` drops and recreates the
  development database (it asks for confirmation).
- `KAFKA_ENABLED=false` dispatches events in-process, so you can work without Kafka.

The seeded accounts are real platform accounts. They sign in through the normal login form and are not flagged or
treated differently. Their emails and roles are listed in the README under
[Database migrations & seed data](README.md#database-migrations--seed-data), and their password comes from
`SEED_USER_PASSWORD`.

## Quality gates

`make check` runs lint, type checks and the backend, frontend and contract test suites. Run it before you push.

| Area | Command | What runs |
|---|---|---|
| Backend lint and format | `make lint` / `make format` | Ruff: `ruff check` and `ruff format --check` on `app worker tests` |
| Backend types | `make typecheck` | mypy on `app worker` (with the Pydantic plugin) |
| Backend tests | `make test-api` (or `test-api-unit`, `test-api-integration`) | pytest. Integration tests use the isolated `bountyflow_test` database (`TEST_DATABASE_URL`) and fakeredis. |
| Real Testnet lifecycle (opt-in) | `make test-testnet` | pytest against a running API on Stellar Testnet |
| Frontend lint and format | `pnpm lint` / `pnpm format:check` | ESLint with zero warnings allowed; Prettier |
| Frontend types | `pnpm typecheck` | `tsc -b --noEmit` (strict mode) |
| Frontend unit tests | `make test-frontend` (`pnpm test`) | Vitest + Testing Library |
| End-to-end | `make test-e2e` (`pnpm test:e2e`) | Playwright on desktop, tablet and mobile viewports, against the real API on Testnet. It needs an isolated stack: follow [docs/testing.md](docs/testing.md#running-the-playwright-suite-pnpm-teste2e). |
| Contract | `make contract-test` | `cargo test` |
| Dependencies | `make audit` | `pip-audit` and `pnpm audit --prod` |

### CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and on pushes to `main`:

- **Backend:** Ruff, mypy, migrations (`alembic upgrade head`, `alembic check`, `alembic downgrade base`), pytest
  with coverage, and `pip-audit`.
- **Frontend:** `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`, a check that no sparkle or star icons are
  used, and `pnpm audit --prod`.
- **Contract:** `cargo fmt --all -- --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, and the
  optimized release wasm build with `stellar contract build --locked`. The job installs Stellar CLI 27.0.0 with the
  official `stellar/stellar-cli@v27.0.0` action, because soroban-sdk 28 refuses a plain `cargo build` for the wasm
  target (see [contracts/README.md](contracts/README.md#build-test-deploy)).
- **End-to-end:** the Playwright suite against the Docker Compose backend on Stellar Testnet.

`alembic check` fails when the models and migrations disagree, and the downgrade step fails when a migration
cannot be reversed. Run the contract's `fmt` and `clippy` checks locally too: `make check` does not include them.

## Coding conventions

### Everywhere

- **No simulated, mocked or placeholder data in product code.** The application has no offline or simulated
  mode: every chain action is a real Stellar transaction. Test doubles such as `backend/tests/support/fake_chain.py`
  and fakeredis belong in tests only.
- **Money-related state follows the chain.** A bounty is funded, and a payment confirmed, only from verified
  on-chain state. Amounts, destinations and contract arguments are always derived on the server, never taken from
  the client.
- **Add tests with every change,** and update the docs your change affects. API changes must update
  [docs/api.md](docs/api.md).
- **Never commit secrets** or `.env` files. See [SECURITY.md](SECURITY.md#handling-secrets).

### Backend

- **Logging:** use Logifyx through `app/core/logging.py`: `get_logger(__name__).info("event_name", key=value)`.
  Request, correlation and user IDs are attached automatically. Never log passwords, tokens, cookies, signed XDR
  or email bodies; sensitive field names are redacted, but don't rely on that.
- **Authorization:** declare permissions in `app/core/rbac.py`. Guard routes with `require_permission(...)` and
  services with `ensure_permission(...)`, and add ownership checks in services. The security suite enumerates the
  OpenAPI document, so a new route fails CI until it is classified as public, authenticated or staff, and every
  mutating route must require the CSRF token.
- **Validation:** Pydantic schemas on every body and query. Money is a decimal string, never a float. URL fields
  use `UrlStr`.
- **Schema changes** need an Alembic migration (`make migration m="..."`) with a working downgrade.
- **Events** go through the transactional outbox, and their payloads never carry secrets or raw tokens.
- Ruff settings (line length 110, Python 3.12 target) are in `backend/pyproject.toml`.

### Frontend

- TypeScript in strict mode. Prettier (`.prettierrc.json`) and ESLint (`eslint.config.js`) settle formatting and
  lint questions.
- Decorative sparkle and star icons are banned (ESLint rule and CI check). Use a meaningful lucide icon.
- **Accessibility:** keep keyboard navigation and visible focus working. `e2e/a11y.spec.ts` runs axe-core
  (WCAG 2.1 A/AA) on key pages in every viewport and fails on serious or critical violations.
- **Design and motion:** follow [docs/design.md](docs/design.md). Most motion is small CSS transitions. The public
  site adds Lenis, the GSAP scroll stories (`useScrollStory`) and the lazy Three.js scenes (`components/three`).
  Every animation respects `prefers-reduced-motion`, and content renders in its final state. See
  [docs/development.md](docs/development.md#design-system-and-motion).
- **Loading skeletons** are captured from the real pages with boneyard. With the app and a seeded API running,
  regenerate them with `pnpm bones` or `make bones` (`pnpm bones --force` recaptures everything). `src/bones` is
  generated output: don't edit it by hand.
- Every `VITE_` variable is public. `VITE_ENABLE_TEST_WALLET` is for the Playwright suite only.

### Contract

- Keep `cargo fmt` and `cargo clippy -D warnings` clean and add a unit test for every behaviour change.
- A contract change only takes effect after a redeploy (`make contract-deploy-testnet`), which rewrites
  `contracts/deployments/testnet.json`. Say so in the pull request.

## Branches, commits and pull requests

**Branches.** Branch from `main` and use a short, descriptive name with a type prefix, for example
`feat/milestone-escrows`, `fix/refresh-race` or `docs/testing-guide`.

**Commits.** Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <summary in the imperative, lower case, no full stop>
```

- Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`.
- Scopes follow the layout: `backend`, `worker`, `frontend`, `contract`, `infra`, `docs`, `ci`.
- Mark breaking changes with `!` after the scope, or a `BREAKING CHANGE:` footer.

For example: `fix(backend): reject refresh tokens bound to another session`.

**Pull requests.** Keep each one focused on a single change. In the description, explain what changed and why, how
you tested it, and link the related issue. Include screenshots for UI changes (desktop and mobile).

### Pull request checklist

- [ ] `make check` passes locally.
- [ ] New or changed behaviour has tests.
- [ ] Schema changes include an Alembic migration that upgrades and downgrades cleanly.
- [ ] API changes are reflected in `docs/api.md`, and other affected docs are updated.
- [ ] New routes are classified in the RBAC and route tests; mutating routes require the CSRF token.
- [ ] Logging goes through Logifyx and never includes secrets or tokens.
- [ ] No mocked or placeholder data in product code, and no secrets or `.env` files in the diff.
- [ ] UI changes work with the keyboard, under reduced motion, and at 375, 768 and 1280 px; skeletons are
      recaptured with `pnpm bones` if the layout changed.
- [ ] Contract changes pass `cargo fmt`, `cargo clippy` and `cargo test`, and the pull request says whether a
      redeploy is needed.

## Licence

BountyFlow is released under the [MIT License](LICENSE). By contributing, you agree that your contributions are
licensed under the same terms.
