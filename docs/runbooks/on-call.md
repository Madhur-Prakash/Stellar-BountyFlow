# On-call handbook

What you own for the length of the shift, what to look at, and what to do first when something fires.

## What you own

| You own | You do not own |
|---|---|
| The API, the worker, PostgreSQL, Redis, Kafka. | Product decisions about a bounty or a dispute. |
| Escrow settlement: that submitted transactions reach `CONFIRMED` or `FAILED`, and that the database matches the contract. | Voting on a dispute. That is the arbiter set, and it needs a quorum. |
| Deciding severity and running the incident until you hand it over. | Upgrading the escrow contract. That is a planned ceremony ([contract-upgrade.md](contract-upgrade.md)). |
| Escalating. | Rotating the escrow admin key alone. |

You do not need to fix everything. You need to stop the bleeding, keep money correct, and get the right person.

## Access you need before the shift starts

Confirm each of these works *before* you are on call, not at 03:00.

| Access | What for |
|---|---|
| Grafana and Prometheus | The dashboard and the alert state. |
| An admin or staff BountyFlow account with `SYSTEM_HEALTH` | `GET /api/v1/admin/ops/status`, the admin console. |
| `METRICS_TOKEN` | Scraping `/metrics` by hand when Grafana is the thing that is broken. |
| Shell on the host, or `docker compose exec` | Logs, `psql`, the Kafka CLI. |
| PostgreSQL credentials (read at minimum; write for the documented SQL here) | Diagnosing and requeuing outbox rows. |
| The log platform | `LOG_JSON=true` output; search by `correlation_id` and `request_id`. |
| The Stellar network provider's console or status page | Telling an outage apart from our own bug. |
| The incident channel and the status page | Comms. |

You do **not** get: the escrow contract admin key, the arbiter signer keys, or `STELLAR_SPONSOR_SECRET`. Those
sit with their named holders ([secret-rotation.md](secret-rotation.md)).

## Daily checks

Five minutes, once per shift. Everything here is on the BountyFlow Grafana dashboard.

1. **Money.** `bountyflow_reconciliation_mismatches` and `bountyflow_reconciliation_foreign_escrows` are both 0,
   and the last audit is recent (`bountyflow_reconciliation_last_run_timestamp_seconds`).
2. **Settlement.** `bountyflow_chain_transaction_oldest_pending_age_seconds` is small (seconds to a couple of
   minutes) and `bountyflow_chain_transactions_pending` is not growing.
3. **Events.** `bountyflow_outbox_backlog` near zero, `bountyflow_outbox_dead_lettered_events` exactly zero,
   `bountyflow_kafka_consumer_lag` small for every consumer.
4. **Workers.** `bountyflow_workers_alive >= 1` and no job in the freshness table is red.
5. **Sponsor.** `bountyflow_sponsor_balance_xlm` is comfortably above `bountyflow_sponsor_low_balance_threshold_xlm`.

## Weekly checks

- A backup from the last 24 hours exists and its checksum verifies
  ([postgres-backup-restore.md](postgres-backup-restore.md)).
- `bountyflow_sanctions_list_age_seconds` is under a day and `bountyflow_sanctions_list_error` is 0.
- `bountyflow_data_exports_failed` and `bountyflow_account_deletions_overdue` are 0.
- `bountyflow_attestations{status="FAILED"}` is 0 and `bountyflow_attestation_oldest_pending_age_seconds` is small.
- `bountyflow_github_rate_limited` is 0, or you know why it is not.
- No alert has been firing continuously all week. A permanently firing alert is a broken alert.
- Skim the API error rate and p95 trend for a slow slide nobody paged on.

## Dashboards and endpoints

| Thing | Where |
|---|---|
| Grafana dashboard | `BountyFlow` folder → **BountyFlow** (`deploy/grafana/bountyflow-dashboard.json`) |
| Alert rules | [`deploy/prometheus/alerts.yml`](../../deploy/prometheus/alerts.yml) |
| Readiness | `GET /health/ready` — per-dependency `ok` / `error` / `disabled`; 503 only when the database is down |
| Liveness | `GET /health/live` |
| Ops snapshot | `GET /api/v1/admin/ops/status` — job health, worker heartbeats, consumer lag, the last reconciliation audit |
| Raw metrics | `GET /metrics` at the origin root, bearer `METRICS_TOKEN` |

```bash
# Metrics by hand (the endpoint answers 404, not 401, when the token is wrong).
curl -s -H "Authorization: Bearer $METRICS_TOKEN" http://127.0.0.1:8000/metrics | grep bountyflow_reconciliation

# The ops snapshot, as a staff user (bf_access cookie from a signed-in session).
curl -s -b "bf_access=$TOKEN" http://127.0.0.1:8000/api/v1/admin/ops/status | jq
```

## Periodic jobs

Every job takes a Redis lock, so only one worker replica runs it at a time. Each one reports through
`bountyflow_worker_job_*{job="…"}`.

| `job` label | Interval | What stops if it stops |
|---|---|---|
| `tx-reconciliation` | 20 s | Submitted transactions are never verified. Funding and payouts never confirm. |
| `review-clock` | 30 s | Contributors are never told their review window passed and they can claim. |
| `github-pr-recheck` | 30 s | Linked pull requests stop being re-checked. |
| `asset-operations` | 30 s | Trustline and asset-contract deployments never confirm. |
| `bounty-lifecycle` | 60 s | Expired bounties are not expired; no deadline-approaching notices. |
| `attestation-pipeline` | 10 s | Completion attestations are never signed or submitted. |
| `data-exports` | 10 s | Users' data exports are never built. |
| `account-deletion` | 300 s | Scheduled deletions never complete. |
| `saved-search-digests` | 300 s | Saved-search digests are not sent. |
| `reconciliation-audit` | 600 s | Nothing compares the contract with the database. |
| `attestation-backfill` | 600 s | Old completions never get an attestation. |
| `skill-graph` | 1800 s (`DISCOVERY_GRAPH_REFRESH_SECONDS`) | Recommendations go stale. |
| `attestation-reconciliation` | 1800 s | On-chain revocations are not picked up. |
| `sanctions-list-refresh` | `SANCTIONS_LIST_REFRESH_SECONDS` (21600 s) | The sanctions list goes stale. Screening keeps working on what is loaded. |

The outbox relay and the Kafka consumers are supervised the same way but are not periodic jobs, so they have no
`bountyflow_worker_job_*` series. Watch `bountyflow_outbox_backlog` and `bountyflow_kafka_consumer_lag` instead.

## Alert → first action

| Alert | First thing to do |
|---|---|
| `BountyFlowForeignEscrow` | **Stop.** SEV1. Do not reconcile. [reconciliation-mismatch.md](reconciliation-mismatch.md). |
| `BountyFlowReconciliationMismatch` | SEV1 until you know which escrows and which fields. [reconciliation-mismatch.md](reconciliation-mismatch.md). |
| `BountyFlowTransactionStuck` | Check `bountyflow_dependency_up{dependency="soroban_rpc"}`. If the RPC is down: [rpc-outage.md](rpc-outage.md). If not, look for `tx-reconciliation` failing. |
| `BountyFlowDependencyDown{dependency="soroban_rpc"}` | [rpc-outage.md](rpc-outage.md). Confirm with the provider's own health endpoint before blaming us. |
| `BountyFlowDependencyDown{dependency="database"}` | SEV1. [postgres-backup-restore.md](postgres-backup-restore.md). |
| `BountyFlowDependencyDown{dependency="redis"}` | Periodic jobs fail closed and stop. No financial state is lost. Restart Redis; see the Redis section of [postgres-backup-restore.md](postgres-backup-restore.md). |
| `BountyFlowDependencyDown{dependency="kafka"}` | The outbox buffers. Watch `bountyflow_outbox_backlog` and fix Kafka. [kafka-lag-and-dlq.md](kafka-lag-and-dlq.md). |
| `BountyFlowNoWorkersAlive` | Is the worker container running? `docker compose ps worker`, then `docker compose logs --tail=200 worker`. |
| `BountyFlowWorkerJobStale` / `BountyFlowWorkerJobFailing` | Find `periodic_job_failed` for that `job` in the worker logs. A job that fails on every run has a broken dependency, not a flaky run. |
| `BountyFlowOutboxDeadLettered` | Read `last_error` on those rows. Fix the cause, then requeue: [kafka-lag-and-dlq.md](kafka-lag-and-dlq.md). |
| `BountyFlowOutboxStalled` / `BountyFlowOutboxBacklog` | Worker alive? Kafka up? [kafka-lag-and-dlq.md](kafka-lag-and-dlq.md). |
| `BountyFlowKafkaConsumerLag` | Which consumer. Is it crash-looping, or just behind after a restart? |
| `BountyFlowApiErrorRateCritical` | Find the route with `sum by (route) (rate(bountyflow_http_requests_total{status=~"5.."}[5m]))`, then the stack traces in the logs. |
| `BountyFlowSponsorStopped` | Fee bumps are refused (users pay their own fee) and passkey smart wallets cannot transact at all. Top up the sponsor account. |
| `BountyFlowSponsorBalanceLow` | Top up before it hits `SPONSOR_MIN_BALANCE_XLM`. Ticket, not a page. |
| `BountyFlowAttestationPipelineStuck` / `BountyFlowAttestationsFailed` | Completions are not reaching the registry. Check the attester key still matches the registry's `attester()` and that its account is funded ([secret-rotation.md](secret-rotation.md)). |
| `BountyFlowAttestationReconciliationMismatch` / `…Missing` | Reputation records, not money. Ticket. |
| `BountyFlowGitHubRateLimited` | Pull request verification is paused. Set or refresh `GITHUB_TOKEN`. Ticket. |
| `BountyFlowDataExportsFailing` / `BountyFlowAccountDeletionsOverdue` | Regulatory clock. Ticket with compliance copied. |
| `BountyFlowSanctionsListError` / `BountyFlowSanctionsListStale` | The sync fails static — existing entries keep blocking. Fix the source. |
| `BountyFlowMetricsCollectorFailing` | Every gauge from that collector is missing, so its alerts are silently not firing. Treat it as loss of visibility. |

## Commands you will want

```bash
# What is running.
docker compose ps

# Recent worker and API logs.
docker compose logs --tail=200 -f worker
docker compose logs --tail=200 -f api

# The log events worth grepping for (docs/security.md lists why).
docker compose logs --since=1h api worker | grep -E \
  'foreign_escrow_detected|escrow_id_rotated|confirmed_transaction_on_foreign_escrow|payout_not_reflected_on_chain'
docker compose logs --since=1h api worker | grep -E \
  'outbox_event_dead_lettered|rate_limit_unavailable|refresh_token_reuse_detected|event_dead_lettered'

# A psql shell (managed service: psql "$DATABASE_URL" with the +psycopg prefix removed).
docker compose exec postgres psql -U bountyflow -d bountyflow

# Restart just the application containers; infrastructure and data volumes are untouched.
docker compose restart api worker
```

Useful SQL for a quick read of the state:

```sql
-- Transactions submitted and not yet resolved, oldest first.
SELECT id, bounty_id, transaction_type, status, submitted_at, transaction_hash
FROM blockchain_transactions
WHERE status = 'SUBMITTED'
ORDER BY submitted_at
LIMIT 20;

-- Outbox: what is waiting and what was given up on.
SELECT count(*) FILTER (WHERE published_at IS NULL)                          AS unpublished,
       count(*) FILTER (WHERE published_at IS NOT NULL AND retry_count >= 25) AS dead_lettered,
       min(created_at) FILTER (WHERE published_at IS NULL)                    AS oldest_unpublished
FROM outbox_events;

-- Live escrows and what they hold, by asset.
SELECT asset_identifier,
       count(*) AS escrows,
       sum(funded_amount - paid_out_amount - refunded_amount) AS held
FROM bounty_escrows
WHERE state IN ('AWAITING_FUNDING', 'FUNDED', 'CANCEL_REQUESTED', 'DISPUTED')
GROUP BY asset_identifier;
```

## Escalation path

1. **You**, for 30 minutes on a SEV1 or SEV2. If you have not understood it by then, escalate — that is not a
   failure, it is the process.
2. **Secondary on-call**, for a second pair of eyes or to take IC while you keep debugging.
3. **The owner of the area**: database and infrastructure, backend, or contracts.
4. **Key holders**, and only for what needs them:
   - Escrow contract admin key — only for a planned upgrade or a suspected compromise.
   - Arbiter quorum — only to resolve a dispute. It needs `STELLAR_ARBITER_THRESHOLD` signers, so start early.
   - Sponsor key holder — to top up or rotate the fee sponsor account.
5. **Compliance and legal** for anything touching sanctions screening, data exports or account deletion.

Escalate immediately, without the 30 minutes, when: funds are provably stuck, a foreign escrow was adopted, a
`contract_upgraded` event fired that nobody planned, or a secret may have leaked.

## Handover checklist

Post this in the channel at the end of the shift.

- [ ] Anything still firing, and why it is acceptable to leave it.
- [ ] Anything silenced, what the silence covers, and when it expires.
- [ ] Open incidents, their severity, IC, and the next expected update.
- [ ] Anything changed by hand during the shift: config, SQL, restarts — with the reason.
- [ ] Anything degraded but not alerting (a job you are watching, a backlog draining).
- [ ] Backups: the last successful one, and whether its checksum verified.
- [ ] Tickets raised, with links.
- [ ] Anything the next person should watch in the first hour.
