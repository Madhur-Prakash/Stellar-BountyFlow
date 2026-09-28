# Development

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 | 24+ | Postgres, Redis, Kafka, Mailpit (and the full stack) |
| GNU Make + bash | 4.x | `make` targets (Git Bash on Windows) |
| uv | 0.9+ | Python 3.12 environment for the backend |
| Node.js + pnpm | 22 / 10+ | Frontend |
| Rust + `wasm32v1-none` target + Stellar CLI | stable / 27 | Contract build, test and deploy only |
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

Alternatively, run everything in containers with `make up` (app on http://localhost:3000).

### Seeded accounts

The seed creates regular accounts that sign in through the normal login form at http://localhost:5173/login:

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

Every account uses the password in `SEED_USER_PASSWORD` (default `BountyFlow!2026`). `make seed` prints this list.

To try the full escrow flow, sign in as Ada, connect a funded Testnet wallet, and fund one of her bounties.
Then sign in as Kai in another browser profile to apply, submit work, and receive the payout.

### Seeding

`make seed` (or `SEED_ON_STARTUP=true`) is **idempotent**: existing records are kept and only missing accounts and
bounties are created. Accounts created by an older seed are renamed in place to the current usernames and emails.

- It creates users, profiles, open and draft bounties, and applications. They are ordinary records with no special
  flag.
- It refuses to run in staging or production.
- It never fabricates chain history. Funding and payouts happen only when a real wallet signs a Stellar
  transaction.

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

### Motion

GSAP is the only animation library (`src/lib/gsap.ts` registers the shared plugins and the house eases
`bf-settle` and `bf-snap`). Reusable pieces live in `src/components/motion/`:

| Piece | What it does |
|---|---|
| `SplitHeading` | SplitText heading: characters rise out of masked lines, optionally widening along the font's width axis |
| `Reveal` | Children rise in groups as they scroll into view (ScrollTrigger.batch); each element animates once |
| `CountUp` | Counts a figure up on first view; later changes tween from the value on screen |
| `Scramble` | Contract ids and hashes resolve out of base32 characters (ScrambleText) |
| `DragRail` | Horizontal rail you grab and throw (Draggable + Inertia, snaps to cards); native scroll on touch |
| `burstCoins` (`src/lib/coin-burst.ts`) | Physics2D coin burst, used only when a transaction that moved money confirms |
| `switchTheme` (`src/lib/theme-transition.ts`) | Light/dark switch that grows from the toggle (View Transitions API), with a colour fade fallback |

The landing page combines them: the hero's reward floor (`RewardPool`: coins rise onto the floor, can be thrown,
lean away from the cursor, and show their bounty on hover), the pinned "How a bounty moves" story with its scrubbed
handoff from the requester's track to the contributor's, and the pinned escrow diagram, where a ring follows the
bounty from state to state and each state explains itself on hover or focus.

Pinned, scroll-scrubbed sections must be created against the scroll engine they will live with: they read
`useScrollEngineReady()` and create their ScrollTrigger only once it returns a value, and they pin a plain block
element (ScrollTrigger disables pin spacing when the pin's parent is a flex container). Rebuilding a pin after the
engine changes leaves a nested pin spacer that breaks the layout below it.

Smooth scrolling (`src/hooks/useSmoothScroll.ts`) runs one engine at a time: ScrollSmoother on the story pages
(landing, how it works, about), which enables `data-speed` parallax, and Lenis everywhere else, so sticky panels
and dialogs keep native behaviour. `src/lib/scroll.ts` scrolls through whichever engine is active.

Every animation checks `motionAllowed()` (`src/hooks/useReducedMotion.ts`). Under `prefers-reduced-motion`, and while
skeletons are being captured, nothing animates and content renders in its final state. Unit tests run as a
reduced-motion user.

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

All variables are documented in [`.env.example`](../.env.example). Key switches:

| Variable | Effect |
|---|---|
| `BLOCKCHAIN_MODE` | `testnet` (default); `mainnet` is reserved for a separate, audited deployment |
| `RUN_MIGRATIONS_ON_STARTUP` | API runs `alembic upgrade head` on boot (advisory-locked) |
| `SEED_ON_STARTUP` | API runs the idempotent seed on boot (skipped in staging/production) |
| `KAFKA_ENABLED` | `false` dispatches events in-process (no Kafka needed) |
| `SEED_USER_PASSWORD` | Password given to seeded accounts (development only) |
| `EMAIL_BACKEND` | `smtp` (Mailpit locally) or `console` |

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
