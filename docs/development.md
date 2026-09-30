# Development

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [Testing](testing.md) &middot; [Database](database.md) &middot; [Deployment](deployment.md)
<!-- nav -->

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 | 24+ | Postgres, Redis, Kafka, Mailpit (and the full stack) |
| GNU Make + bash | 4.x | `make` targets (Git Bash on Windows) |
| uv | 0.9+ | Python 3.12 environment for the backend |
| Node.js + pnpm | 22.12+ / 11 (pinned in `package.json`) | Frontend |
| Rust + `wasm32v1-none` target + Stellar CLI | stable / 27 (25.2.0+ required; CI pins 27.0.0) | Contract build (`stellar contract build`), test and deploy only |
| Freighter browser extension | latest | Signing on Testnet |

## First run

```bash
make install        # creates .env (fresh JWT secret), uv sync, pnpm install, Playwright browser
make dev            # infra in Docker; migrate + seed; API :8000, worker, Vite :5173
```

| URL | What |
|---|---|
| http://localhost:5173 | App (Vite dev server, proxies `/api` to :8000) |
| http://localhost:8000/api/docs | OpenAPI / Swagger UI |
| http://localhost:8025 | Mailpit (verification and reset emails land here) |
| http://localhost:8080 | Kafka UI (`make up-tools`) |

Alternatively, run everything in containers with `make up`. It serves the app on
http://localhost:5173 too — the same address as the dev server, so a link in a verification email resolves
whichever way the app is running (`FRONTEND_HOST_PORT`).

To run the application yourself against containerised infrastructure, `make infra` starts every service
**except** the frontend and the backend (the API, the worker and the migration job). It is defined by
exclusion, so a service added to `docker-compose.yml` is included without anyone having to remember to
update the target.

### Seeded accounts

The seed creates 64 regular accounts that sign in through the normal login form at
http://localhost:5173/login. These eight are the ones worth knowing — one of every role, plus both sides of the
marketplace — and they are the ones `make seed` prints:

| Email | Role | What the account has |
|---|---|---|
| `ada.okafor@bountyflow.test` | User | Posts bounties (requester) |
| `nova.labs@bountyflow.test` | User | Posts bounties (requester) |
| `kai.tanaka@bountyflow.test` | User | Applies to bounties (contributor) |
| `river.chen@bountyflow.test` | User | Contributor |
| `mira.kovac@bountyflow.test` | User | Contributor |
| `sol.adeyemi@bountyflow.test` | User | Contributor |
| `priya.nair@bountyflow.test` | Moderator | Moderation queue, disputes |
| `morgan.reyes@bountyflow.test` | Admin | Admin console, users, roles, audit log |

The other 56 accounts are requesters and contributors who fill the marketplace, the application queues and the
feedback inbox. Their addresses follow the same pattern (`first.last@bountyflow.test`) and you can read them off
a bounty, a profile page or the admin user list.

Every account uses the password in `SEED_USER_PASSWORD` (default `BountyFlow!2026`). `make seed` prints the
eight above.

To try the full escrow flow, sign in as Ada, connect a funded Testnet wallet, and fund one of her bounties.
Then sign in as Kai in another browser profile to apply, submit work, and receive the payout.

### Seeding

`make seed` (or `SEED_ON_STARTUP=true`) is **idempotent**: existing records are kept and only missing accounts and
bounties are created. Accounts created by an older seed are renamed in place to the current usernames and emails.

- It creates 64 users with profiles and skills, 70 bounties across every category and difficulty (61 open, 9
  draft), 154 applications, Q&A threads, bookmarks, saved searches, product feedback and a few announcements.
  They are ordinary records with no special flag.
- Bounties are keyed by `metadata.seed_key` and everything else by a deterministic UUID, so a second run creates
  nothing.
- It refuses to run in staging or production.
- It never fabricates chain history. No escrow, payment, blockchain transaction or attestation row is ever
  written, and a seeded bounty never gets past `open`. Funding and payouts happen only when a real wallet signs
  a Stellar transaction.

### Using Testnet

1. Install Freighter and switch it to **Testnet**.
2. Fund your address: `https://friendbot.stellar.org/?addr=G...`.
3. In the app: **Settings → Wallets → Connect Freighter**, then sign the ownership challenge. It is not a
   transaction and costs nothing.
4. Fund a bounty and sign the escrow transaction in Freighter. The transaction appears with a StellarExpert link
   once it's verified.

## Backend

```bash
cd backend
uv run python -m app.serve         # API (selector event loop; required on Windows)
uv run python -m worker.main       # worker
uv run alembic revision --autogenerate -m "..."
uv run ruff check app worker tests && uv run mypy app worker
```

On Linux/macOS or in containers you can also run `uv run uvicorn app.main:app --reload`. On Windows, psycopg's
async driver cannot use the default Proactor event loop, so use `app.serve`.

### Logging

The backend logs through **Logifyx** (`app/core/logging.py`). App code calls
`get_logger(__name__).info("event_name", key=value)`. The request ID, correlation ID, user ID and service name are
attached automatically. Sensitive field names are redacted, and Logifyx masks secrets in messages. Control output
with `LOG_LEVEL`, `LOG_JSON=true` (single-line JSON) and `LOG_OUTPUT` (`console` | `file` | `both` | `none`).

## Frontend

```bash
cd frontend
pnpm dev | pnpm build | pnpm lint | pnpm typecheck | pnpm test | pnpm test:e2e | pnpm bones
```

### Design system and motion

The visual rules (tokens, type scale, layout patterns, what motion is allowed) are in
[design.md](design.md). In short: bold Bricolage Grotesque headlines over Geist on warm paper (or warm
near-black), one blue accent carrying every action and status tag, green kept for confirmations of verified
on-chain facts, and motion that answers an action rather than decorating the page.

Small transitions are CSS (`tw-animate-css` utilities), such as the route fade (`AnimatedOutlet`) and the
mobile menu's link stagger.

The landing page's two scroll stories use `src/hooks/useScrollStory.ts`. A tall wrapper holds a
`position: sticky` stage, and a GSAP timeline is scrubbed across the wrapper by ScrollTrigger. GSAP,
ScrollTrigger and DrawSVG are imported on first use, so other pages never download them. GSAP only animates
wrappers, fills and SVG masks; anything with state classes (active or done steps) is rendered by React from the
reported progress, so the two never write the same styles.

The decorative 3D scenes live in `src/components/three` (Three.js with React Three Fiber). `<Scene name="globe" | "ledger">`
lazy-loads a scene after the page settles, only where WebGL is available and never during skeleton capture. The
scenes read their colours from the theme tokens, stop their frame loop when off screen, and draw a still frame
under reduced motion.

Radix handles dialog, menu, popover and sheet transitions. The theme switch (`switchTheme` in
`src/lib/theme-transition.ts`) grows the new theme from the toggle with the View Transitions API, and falls back
to a short colour fade.

Smooth scrolling (`src/hooks/useSmoothScroll.ts`) is Lenis on the native window scroll. Only the public site uses it.
The signed-in workspace keeps plain native scrolling, which suits long tables and forms. `src/lib/scroll.ts`
scrolls through Lenis when it is active and natively otherwise.

Every animation checks `motionAllowed()` (`src/hooks/useReducedMotion.ts`). Under `prefers-reduced-motion`, and
while skeletons are being captured, nothing animates and content renders in its final state. Unit tests run as a
reduced-motion user.

### Lazy loading

- **Routes:** every route is its own chunk (`router.tsx`).
- **Heavy components inside pages:**
  - charts (recharts)
  - the Markdown renderer (`SafeMarkdown`)
  - the wallet SDK (Freighter, loaded on first wallet action)
  - dialogs that are only needed on demand
  - GSAP for the scroll stories
  - Three.js for the landing scenes
- **How:** each is behind `React.lazy` or a dynamic `import()`, with a fallback that keeps the layout from shifting.

### Loading skeletons

Loading states use [boneyard](https://github.com/0xGF/boneyard) bones captured from the real pages. Give a
`QueryView` a unique `skeleton` name, or wrap a region in `<Bones name loading fallback>`, then regenerate:

```bash
pnpm bones        # app + seeded API running; add --force to recapture everything
```

`scripts/capture-bones.mjs` signs in as seeded accounts (Ada for the workspace, Kai for contributor lists, Morgan
for the staff console) and captures each page at 390, 768 and 1280 px into `src/bones`. Each view loads only its
own bones, on demand (`src/components/layout/Bones.tsx`). A view that is empty for its account has nothing to
capture and keeps its generic fallback skeleton. Colours and animation are set in `boneyard.config.json`.

## Environment

**One file, at the repository root.** The backend, Docker Compose and the frontend all read the same `.env`,
documented in [`.env.example`](../.env.example). There is no `frontend/.env`.

### Which side reads what

| Consumer | Variables | Notes |
|---|---|---|
| **Frontend** | The four `VITE_*` keys, and nothing else | Vite is configured with `envDir` pointing at the repository root and `envPrefix: 'VITE_'`, so it reads the `VITE_` prefix alone — no backend variable is loaded at build time, let alone shipped |
| **Backend** | Everything else except the eight below | Read by `Settings` in `app/core/config.py` and validated at startup |
| **Docker Compose** | `API_HOST_PORT`, `FRONTEND_HOST_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Port mappings and the Postgres container's own init; neither application reads them |
| **Tests only** | `TEST_DATABASE_URL`, `E2E_ARBITER_SECRETS` | Never used by a running app |

### The frontend's four

| Variable | In the bundle? | Effect |
|---|---|---|
| `VITE_API_BASE_URL` | **Yes** | API base as the browser sees it. Default `/api/v1` — same origin, proxied by Vite in development and nginx in Docker. In Docker it is baked in at image build (`frontend/Dockerfile` `ARG`), so changing it needs a rebuild |
| `VITE_GITHUB_URL` | **Yes** | Public repository URL shown in the footer |
| `VITE_API_PROXY_TARGET` | No | Development server only: where Vite proxies `/api` and `/health` |
| `VITE_ENABLE_TEST_WALLET` | No | End-to-end tests only. A production `vite build` **refuses to run** with it set |

Anything prefixed `VITE_` is inlined into the JavaScript bundle at build time and is therefore public
forever. Never put a secret behind one.

### Key backend switches

| Variable | Effect |
|---|---|
| `BLOCKCHAIN_MODE` | `testnet` (default); `mainnet` is reserved for a separate, audited deployment |
| `RUN_MIGRATIONS_ON_STARTUP` | API runs `alembic upgrade head` on boot (advisory-locked) |
| `SEED_ON_STARTUP` | API runs the idempotent seed on boot (skipped in staging/production) |
| `KAFKA_ENABLED` | `false` dispatches events in-process (no Kafka needed) |
| `SEED_USER_PASSWORD` | Password given to seeded accounts (development only) |
| `EMAIL_BACKEND` | `smtp` (Mailpit locally), `console`, or `gmail` |
| `GMAIL_CREDENTIALS_B64`, `GMAIL_SENDER`, `EMAIL_FROM_NAME` | Send real email through the Gmail API. Setting the credential is enough — it takes precedence over the SMTP default. Mint it with `uv run python scripts/mint_gmail_token.py` (needs `uv sync --group dev`). |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Psycopg cannot use the 'ProactorEventLoop'` | Start the API with `python -m app.serve` (not plain uvicorn) on Windows. |
| `503` / "On-chain escrow is not configured" | Set `SOROBAN_CONTRACT_ID` and `STELLAR_NATIVE_ASSET_CONTRACT_ID` (defaults are in `.env.example`). |
| `account_not_found` when funding | Fund the wallet with Friendbot on Testnet. |
| `wallet_not_verified` | Connect and verify the wallet in Settings first. |
| Publishing returns `email_not_verified` | Open the email in Mailpit (http://localhost:8025) and click the link. |
| Kafka connection errors on the host | Use `KAFKA_BOOTSTRAP_SERVERS=localhost:9094` (the external listener). |
| Port already in use | Change `*_HOST_PORT` variables in `.env`. |
