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

## Mainnet

Mainnet is a **separate, future deployment target**:

1. Audit the contract and deploy it to mainnet with a **multisig arbiter**.
2. Set `BLOCKCHAIN_MODE=mainnet`, the mainnet passphrase (the config validator enforces it), and mainnet
   Horizon/RPC/explorer URLs.
3. Use fresh databases. Testnet data must never be migrated to mainnet.

## Scaling

- The API is stateless; scale it horizontally. Startup migrations and seeding are serialised by an advisory lock.
- Workers scale by consumer group. Kafka partitions (3 per topic) bound consumer parallelism. Periodic jobs are
  single-flight through Redis locks.
- Redis is a cache. Losing it degrades performance and rate limiting but never corrupts financial state.
