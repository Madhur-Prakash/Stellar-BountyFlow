# Release and rollback

How a BountyFlow release goes out, what gates it, and how to get back when it goes wrong. The short version:
**roll back code freely, roll back migrations almost never.**

## What ships

| Image | Dockerfile | Runs |
|---|---|---|
| API | `backend/Dockerfile` | `uvicorn app.main:app` as uid 10001 |
| Worker | `backend/Dockerfile.worker` | `python -m worker.main` |
| Frontend | `frontend/Dockerfile` | nginx serving `dist/`, proxying `/api` and `/health` |

The API and the worker are built from the same backend context, so migrations always match the code that is
about to run. The compose `migrate` service uses the API image for exactly that reason.

## Build and tag

```bash
make check                 # lint, typecheck, backend + frontend + contract tests
docker compose build       # or your registry build
```

Tag every image with the **commit sha**, and only additionally with a moving tag:

```bash
docker build -t registry.example.com/bountyflow-api:$(git rev-parse --short HEAD) backend
docker tag registry.example.com/bountyflow-api:<sha> registry.example.com/bountyflow-api:latest
```

Rolling back means re-deploying a sha. If the only tag is `latest`, there is nothing to roll back to. Record the
sha currently in production somewhere you can read during an incident; the API also reports it:

```bash
curl -s -H "Authorization: Bearer $METRICS_TOKEN" http://127.0.0.1:8000/metrics | grep bountyflow_build_info
# bountyflow_build_info{version="…",env="production",network="mainnet"} 1
```

## Release steps

1. **Back up first.** A fresh dump, checksum verified
   ([postgres-backup-restore.md](postgres-backup-restore.md)). Not negotiable for a release that migrates.
2. **Migrate.** Run `alembic upgrade head` as an explicit release step, before the new code starts:

   ```bash
   docker compose run --rm migrate
   # or, directly:
   cd backend && uv run alembic upgrade head
   ```

   `RUN_MIGRATIONS_ON_STARTUP=true` also works and is safe with several replicas — the step runs under a
   Postgres advisory lock. Prefer the explicit step in production: you want to see the migration succeed or fail
   on its own, not tangled up with a rollout.
3. **Roll out the API**, one instance or a small share first (below).
4. **Health gate.** Do not proceed until the new instance is ready:

   ```bash
   curl -s http://127.0.0.1:8000/health/ready | jq
   ```

   ```json
   {"status": "ok", "checks": {"database": "ok", "redis": "ok", "kafka": "ok", "blockchain_rpc": "ok"}}
   ```

   `/health/ready` answers 503 only when the **database** is down: the API can serve without Kafka (the outbox
   buffers) and without the RPC (chain actions fail cleanly). So read the `checks` map, not just the status
   code. Load balancers should use `/health/live` for liveness and `/health/ready` for readiness.
5. **Roll out the worker.** It stops taking new work on SIGTERM, finishes in-flight events or leaves them
   uncommitted for redelivery, and removes its heartbeat key. Give it the compose `stop_grace_period` of 30 s.
6. **Roll out the frontend.**
7. **Watch** (below), then complete or roll back.

## Canary

Run the new API image on a small share of traffic — one instance, or a weighted route — for at least 15 minutes
before the rest.

Promote only when all of these hold on the canary:

| Gate | Signal |
|---|---|
| Ready | `/health/ready` with every check `ok` (or `kafka: disabled` where that is intended) |
| No new 5xx | `sum(rate(bountyflow_http_requests_total{status=~"5.."}[5m]))` flat versus the old instances |
| No unhandled exceptions | `rate(bountyflow_http_unhandled_exceptions_total[5m])` is 0 |
| Latency unchanged | p95 within about 20% of the previous release |
| Chain routes work | one real prepare → sign → submit → confirm on a low-value bounty |
| Events flowing | `bountyflow_outbox_backlog` not growing, `bountyflow_kafka_consumer_lag` steady |
| Jobs healthy | `bountyflow_worker_job_consecutive_failures` all 0 |
| Money correct | after one audit cycle, `bountyflow_reconciliation_mismatches` is 0 |

The worker is harder to canary because periodic jobs are single-flight through Redis locks: two versions will
alternate on the same job. Prefer a straight replace for the worker, after the API canary has passed.

## Rolling back code

This is the normal, cheap path. Deploy the previous sha:

```bash
docker compose pull && docker compose up -d api worker frontend      # with the image tags pinned to the old sha
```

Safe whenever the old code can still read the current schema — which is the case for every migration in this
repository that only **adds** tables, columns or indexes. Expand-and-contract is the rule: add in one release,
use it in the next, remove in a third. That way the previous release always runs against the new schema.

After a code rollback, check the same gates as the canary, and specifically that
`bountyflow_worker_job_consecutive_failures` is 0 — a rolled-back worker meeting a newer schema shows up there
first.

## Rolling back a migration

**Forward-fix is almost always the right answer.** Write a new migration that corrects the problem and deploy
it. `alembic downgrade` is a last resort, and only when the migration's own downgrade is safe for the data that
now exists.

Before ever running `alembic downgrade`:

1. Take a fresh backup and verify its checksum.
2. Read the migration's `downgrade()`. If it drops a table or a column, the data in it is **gone**. There is no
   "downgrade and keep the data".
3. Stop the API and the worker, so nothing writes into a schema that is mid-change.
4. Run one step at a time and check in between:

   ```bash
   cd backend
   uv run alembic current
   uv run alembic downgrade -1
   uv run alembic current
   ```

5. Deploy the matching older code before starting anything.

```bash
# See where you are and what is available.
cd backend
uv run alembic current
uv run alembic history --verbose | head -40
```

### Are the migrations destructive?

"Destructive upgrade" means applying it deletes data. "Destructive downgrade" means reversing it deletes data.
Everything here was read from `backend/migrations/versions/`.

| Revision | What it does | Destructive upgrade? | Destructive downgrade? |
|---|---|---|---|
| `0001_initial_schema` | Creates the whole schema. | No | **Yes** — drops every table. |
| `0002_query_indexes` | Adds query indexes. | No | No — drops only indexes. |
| `0003_remove_simulated_mode` | **Drops** `is_simulated` from several tables and drops `simulated_ledger_entries`. | **Yes** | No — recreates the column and the (empty) table. |
| `0004_remove_demo_flags` | **Drops** `users.is_demo` and `bounties.is_demo`. | **Yes** | No — re-adds the columns, defaulting to false. |
| `0005_wallets` | Adds `passkey_wallets`, `sponsored_transactions`, and `wallet_app` / `proof_method` / `is_primary` on `wallets`. | No | **Yes** — drops those tables and columns. |
| `0006_assets` | Adds `reward_assets`, `asset_operations`, `bounties.reward_asset_identifier`; seeds XLM and Testnet USDC. | No | **Yes** — drops them. |
| `0007_escrow_v2` | Adds `bounty_milestones`, `dispute_votes`, the review-clock columns on `bounty_submissions`, `payment_records.milestone_id`, the v2 escrow columns. | No | **Yes** — drops all of it, including every milestone and arbiter vote. |
| `0008_reputation` | Adds `completion_attestations` and `verifiable_credentials`. | No | **Yes** — drops them, losing the local record of issued credentials. |
| `0009_discovery` | Adds `saved_searches`, `saved_search_matches`, `skill_nodes`, `skill_edges` and the normalised-skill expression indexes. | No | **Yes** — drops them. The skill graph rebuilds itself; saved searches do not. |
| `0010_collaboration` | Adds `bounty_qa_posts`, `bounty_qa_votes`, `github_accounts`, `submission_pull_requests`, `bounties.require_merged_pr`. | No | **Yes** — drops them, losing every Q&A post and GitHub link. |
| `0011_mainnet_readiness` | Adds `data_exports`, `account_deletion_requests`, `screening_entries`, `legal_document_versions`, `legal_acceptances`. | No | **Yes** — drops them, losing sanctions entries and recorded legal acceptances. |

Read it this way:

- **`0003` and `0004` are the only destructive upgrades**, and both are long past. They removed the simulated
  chain mode and the demo flags.
- **Everything from `0005` on is additive on the way up and destructive on the way down.** Downgrading past
  `0011` deletes the sanctions list entries and the record of who accepted which terms version. Downgrading past
  `0008` deletes the local record of issued verifiable credentials — the on-chain attestations survive, the
  credential rows do not. Downgrading past `0007` deletes every milestone and arbiter vote, which are the only
  off-chain record of a dispute's progress.
- No downgrade can undo anything on-chain. The escrow contract does not care what the database says.

If a downgrade would drop a table that has rows, dump that table first:

```bash
docker compose exec -T postgres pg_dump -U bountyflow -d bountyflow \
  --format=custom --table=dispute_votes --table=bounty_milestones > pre-downgrade-tables.dump
```

## Watch after every release

For at least 30 minutes:

```promql
sum(rate(bountyflow_http_requests_total{status=~"5.."}[5m]))
histogram_quantile(0.95, sum by (le) (rate(bountyflow_http_request_duration_seconds_bucket[5m])))
bountyflow_outbox_backlog
bountyflow_kafka_consumer_lag
bountyflow_worker_job_consecutive_failures
bountyflow_chain_transaction_oldest_pending_age_seconds
bountyflow_reconciliation_mismatches
```

and check `bountyflow_build_info` shows the version you meant to deploy on every instance.

The one that needs a full cycle is `bountyflow_reconciliation_mismatches`: the audit runs every 600 seconds, so
give it at least one clean run before you call the release good. A release that breaks verification shows up
there and nowhere else.

## Rollback decision

| Situation | Do |
|---|---|
| Error rate or latency clearly worse on the canary | Roll back the code. Do not debug in production. |
| A migration applied and the new code is broken | Roll back the code only, if the old code can read the new schema — it can for every additive migration here. |
| A migration applied and is itself wrong | Forward-fix with a new migration. Downgrade only if its `downgrade()` is non-destructive (`0002`, `0003`, `0004`). |
| Reconciliation mismatches appear after a release | SEV1. Roll back the code, then follow [reconciliation-mismatch.md](reconciliation-mismatch.md). Do not reconcile anything until the code is back to a known-good version. |
| The worker crash-loops | Roll back the worker image on its own; the API and the worker deploy independently. |
| Chain actions fail after a release | Check whether the RPC is at fault first ([rpc-outage.md](rpc-outage.md)) before blaming the release. |
