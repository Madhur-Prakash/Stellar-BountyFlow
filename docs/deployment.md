# Deployment

## Images

| Image | Dockerfile | Runs |
|---|---|---|
| API | `backend/Dockerfile` | `uvicorn app.main:app` as non-root (uid 10001) |
| Worker | `backend/Dockerfile.worker` | `python -m worker.main` |
| Frontend | `frontend/Dockerfile` | Multi-stage build → nginx serving `dist/` with SPA fallback; proxies `/api` and `/health` to the API; security headers and CSP |

`docker-compose.yml` wires these images together with pinned infrastructure images and health checks, and binds
every port to `127.0.0.1`. It is the reference for a single-host deployment.

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
using it (`bounty_escrows.contract_id`), so superseding a contract does not strand existing escrows — but the
new id must be audited before it can be configured.

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
