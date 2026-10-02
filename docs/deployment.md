# Deployment

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [Development](development.md) &middot; [Runbooks](runbooks/README.md) &middot; [Security](security.md)
<!-- nav -->

## Images

| Image | Dockerfile | Runs |
|---|---|---|
| API | `backend/Dockerfile` | `uvicorn app.main:app` as non-root (uid 10001) |
| Worker | `backend/Dockerfile.worker` | `python -m worker.main` |
| Frontend | `frontend/Dockerfile` | Multi-stage build → nginx serving `dist/` with SPA fallback; proxies `/api` and `/health` to the API; security headers and CSP |

`docker-compose.yml` wires these images together with pinned infrastructure images and health checks, and binds
every port to `127.0.0.1`. It is the reference for a single-host deployment.

## Hosting the frontend separately (Vercel)

The frontend is a static bundle, so it can be served from a CDN with the API on its own host.
[`frontend/vercel.json`](../frontend/vercel.json) holds the build settings, the single-page fallback, cache
policy and the security headers — nginx sets equivalents in the Docker image, and Vercel adds none of them on
its own.

**It is committed on purpose, and it is safe in a public repository.** It carries no credentials: build
commands, a rewrite and response headers are all things a visitor can observe from the outside anyway. It also
has to be in the repository to work, because Vercel reads it from the checkout at build time — there is no
dashboard equivalent for rewrites or headers. The rule is narrower than "don't commit config": **never put a
value in `vercel.json` that you would not publish.** Its `env` and `build.env` keys can hold literals, so a
secret pasted there ships to anyone who can read the repo. Secrets belong in the dashboard, which is why this
file has neither key.

**Project settings:** set **Root Directory** to `frontend`. Everything else comes from the file.

**If a deep link 404s**, the single-page fallback is not reaching the request. The app itself never produces
that page: a route it does not know renders its own "page not found", so Vercel's black `404 NOT_FOUND` screen
means the rewrite never ran. Most links inside the app are client-side navigations and hide the problem; the
ones that surface it are the full document loads — a refresh, a pasted URL, and the terms and privacy links on
the sign-up form, which open in a new tab. Check, in order:

1. **Root Directory is `frontend`.** Vercel reads `vercel.json` only from the root directory, so a project
   rooted at the repository never sees the rewrite.
2. **The deployment is newer than the commit that added `frontend/vercel.json`.** It arrived late; a build from
   before it has no fallback baked in. Redeploy from the dashboard with the build cache cleared.

### What the browser needs

There is no `.env` on Vercel — `.env` is git-ignored. Vite reads `VITE_`-prefixed variables from the
environment, which is exactly what the dashboard injects.

| Set in the Vercel dashboard | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://api.example.com/api/v1` — the API's public origin, including the version prefix |
| `VITE_GITHUB_URL` | Optional; the footer link |

Never set `VITE_ENABLE_TEST_WALLET`: a production `vite build` **refuses to run** with it present. Never set a
backend variable there either — it would not be read, and a secret in one more place is a secret in one more
place.

### What the API must be told in return

The browser now sends session and CSRF cookies to a different origin, so the API has to permit it:

| Backend variable | Value | Why |
|---|---|---|
| `CORS_ORIGINS` | `https://yourapp.vercel.app` | Explicit only. `*` is rejected, because CORS runs with `allow_credentials=True` and a reflected origin would let any site read authenticated responses |
| `COOKIE_SECURE` | `true` | Required in production; the API refuses to start otherwise |
| `COOKIE_SAMESITE` | `none` | `lax` does not send cookies cross-site, so sign-in fails silently |
| `FRONTEND_URL` | `https://yourapp.vercel.app` | Where email links point |
| `CREDENTIAL_ISSUER_DOMAIN` | The **API** host | The API serves `/.well-known/did.json`; it is not a frontend route, and the default derives from `FRONTEND_URL` |

Add every preview domain you intend to sign in from to `CORS_ORIGINS`: Vercel gives each deployment its own
hostname, and an unlisted one fails auth rather than failing loudly.

> **Know the cost of `SameSite=none`.** It makes the session a third-party cookie. Safari blocks those by
> default under Intelligent Tracking Prevention and Chrome restricts them, so a share of visitors will not stay
> signed in. Serving both under one parent domain (`app.example.com`, `api.example.com`) with
> `COOKIE_DOMAIN=.example.com` and `COOKIE_SAMESITE=lax` avoids it entirely, with no code change.

## Production checklist

The API refuses to start in `staging`/`production` unless all of the following are true:

- [ ] `JWT_SECRET` is a strong random value (≥ 32 chars, not a placeholder)
- [ ] `COOKIE_SECURE=true` (serve over HTTPS)
- [ ] `SOROBAN_CONTRACT_ID` is set
- [ ] `WALLET_CHALLENGE_SIGNING_SECRET` is set (a dedicated key that never holds funds)

Also:

- [ ] Set `CORS_ORIGINS` and `FRONTEND_URL` to the real origin(s).
- [ ] Use managed PostgreSQL with backups, managed Redis, and a Kafka cluster with replication factor ≥ 3.
- [ ] Run `alembic upgrade head` as a release step, or set `RUN_MIGRATIONS_ON_STARTUP=true`. Never seed in
      production; seeding is refused automatically.
- [ ] Configure a real SMTP provider (`SMTP_*`, `SMTP_USE_TLS=true`).
- [ ] Set `LOG_JSON=true` and ship stdout to your log platform. Alert on `rate_limit_unavailable`,
      `outbox_event_dead_lettered`, DLQ traffic and `payout_not_reflected_on_chain`.
- [ ] Point load-balancer health checks at `/health/live` and readiness at `/health/ready`.
- [ ] Put TLS and HSTS in front of nginx or the API.

## Observability

`GET /metrics` serves Prometheus text (`app/modules/ops/router.py`). It is outside `/api/v1` and outside the
OpenAPI document, and it answers only:

- requests carrying `Authorization: Bearer $METRICS_TOKEN`, or
- direct loopback requests with no `X-Forwarded-For`, when no token is set.

Anything else gets 404, so the endpoint never advertises itself. The bundled nginx proxies only `/api` and
`/health`, so it is not reachable through the frontend container.

It covers request latency and errors, the outbox backlog, Kafka consumer lag, pending unverified transactions,
chain-versus-database reconciliation mismatches, worker job health and heartbeats, the sponsor balance,
attestation pipeline depth, GitHub rate-limit backoff, and the compliance queues. Staff can read the same
worker state as JSON at `GET /api/v1/admin/ops/status` (needs `system:health`).

Run it locally:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d prometheus grafana
```

Alert rules are in `deploy/prometheus/alerts.yml` and a Grafana dashboard in `deploy/grafana/`. Every alert
links to the runbook that handles it ([docs/runbooks/](runbooks/README.md)).

## Backups

`scripts/backup-db.sh` and `scripts/backup-db.ps1` take a `pg_dump` custom-format backup with a checksum and
retention pruning; `scripts/restore-db.sh` / `.ps1` restore one, and refuse to overwrite an unexpected database
without `--force`. Point-in-time recovery, the Redis-loss procedure and the quarterly drill are in
[docs/runbooks/postgres-backup-restore.md](runbooks/postgres-backup-restore.md) and
[docs/runbooks/restore-drill.md](runbooks/restore-drill.md).

## Mainnet

Mainnet is a **separate deployment target** and the API refuses to start on it until every requirement is met.
Setting `STELLAR_NETWORK=mainnet` (or `BLOCKCHAIN_MODE=mainnet`) runs the guard in `app/core/mainnet.py`, which
collects **every** problem and refuses startup with the full list, so one pass fixes everything:

| Requirement | Setting |
|---|---|
| Explicit opt-in | `ALLOW_MAINNET=true`, `APP_ENV=production` |
| Network | `STELLAR_NETWORK` and `BLOCKCHAIN_MODE` both `mainnet`, the mainnet passphrase, and mainnet Horizon / RPC / explorer URLs |
| Audited contracts | Every configured contract id listed in `deploy/audited-deployments.json` under `mainnet` **with its audit report**: `SOROBAN_CONTRACT_ID`, plus `WEB_AUTH_CONTRACT_ID` and `ATTESTATION_CONTRACT_ID` when those features are on |
| Multisig arbiter | `STELLAR_ARBITER_THRESHOLD` at least 2, with at least that many distinct `STELLAR_ARBITER_ADDRESSES` |
| HTTPS everywhere | `FRONTEND_URL`, `PUBLIC_API_URL` and every `CORS_ORIGINS` entry are `https://`, and `COOKIE_SECURE=true` |
| Real secrets | `JWT_SECRET`, `WALLET_CHALLENGE_SIGNING_SECRET`, `STELLAR_SPONSOR_SECRET`, `STELLAR_ATTESTER_SECRET`, `CREDENTIAL_ISSUER_SECRET` and `METRICS_TOKEN` all set to real values, and a `DATABASE_URL` that is not the development one |
| Sponsor caps | `SPONSOR_DAILY_TX_LIMIT`, `SPONSOR_DAILY_FEE_LIMIT_STROOPS` and `SPONSOR_MIN_BALANCE_XLM` positive, with `SPONSOR_LOW_BALANCE_XLM` above the floor |
| Screening on | `SANCTIONS_SCREENING_ENABLED=true` and a `SANCTIONS_LIST_PATH` or `SANCTIONS_LIST_URL` |
| Test switches off | `SEED_ON_STARTUP`, `GITHUB_FIXTURE_TRANSPORT` and `DISCOVERY_DIGEST_TRIGGER_ENABLED` all false, and `ESCROW_MIN_REVIEW_WINDOW_SECONDS` at least a day |

A contract id in `deploy/audited-deployments.json` counts only when its entry carries an `audit` with a
`report_url`; an id on its own is not evidence of a review. Escrows created on an earlier escrow contract keep
using it (`bountyflow_bounty_escrows.contract_id`), so superseding a contract does not strand existing escrows — but
the new id must be audited before it can be configured.

Also, and not enforceable in code:

1. Use **fresh databases**. Testnet data must never be migrated to mainnet.
2. Complete the compliance review ([docs/compliance.md](compliance.md)) and publish terms and privacy versions
   written for real money.
3. Work through [docs/runbooks/mainnet-launch-checklist.md](runbooks/mainnet-launch-checklist.md), which covers
   the key ceremonies, the funded sponsor account, alerting and a rehearsed rollback.

## Scaling

- The API is stateless; scale it horizontally. Startup migrations and seeding are serialised by an advisory lock.
- Workers scale by consumer group. Kafka partitions (3 per topic) bound consumer parallelism. Periodic jobs are
  single-flight through Redis locks.
- Redis is a cache. Losing it degrades performance and rate limiting but never corrupts financial state.
