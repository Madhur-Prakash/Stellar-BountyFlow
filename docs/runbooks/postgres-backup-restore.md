# PostgreSQL backup, restore and Redis loss

PostgreSQL 17 is the source of truth for everything off-chain. The escrow contract holds the funds and can
always be re-read, but the link between a bounty, a contributor, a submission and an on-chain escrow id lives
only here. Losing it is SEV1.

Redis is a cache. Losing it costs performance and some in-flight state, never money. The second half of this
page says exactly what.

## Backups

`scripts/backup-db.sh` and `scripts/backup-db.ps1` take a `pg_dump` custom-format dump with a timestamped name
and a `.sha256` checksum beside it, and prune their own older files.

```bash
# Local docker compose stack, keeping 14 days.
scripts/backup-db.sh --docker --out-dir /var/backups/bountyflow --retention-days 14

# A managed database.
scripts/backup-db.sh --database-url "postgresql://bountyflow:…@db.example.com:5432/bountyflow" \
  --out-dir /var/backups/bountyflow --retention-days 30

# Windows.
powershell -ExecutionPolicy Bypass -File scripts/backup-db.ps1 -Docker -RetentionDays 14
```

```text
/var/backups/bountyflow/
  bountyflow-bountyflow-20260929T031500Z.dump
  bountyflow-bountyflow-20260929T031500Z.dump.sha256
```

The custom format is what `pg_restore` reads and is already zlib-compressed; `--gzip` exists only for pipelines
that insist on a `.gz`. `--no-owner --no-privileges` is always passed, so a dump restores into a database owned
by a different role.

Verify a backup without restoring it:

```bash
sha256sum -c /var/backups/bountyflow/bountyflow-bountyflow-20260929T031500Z.dump.sha256
pg_restore --list /var/backups/bountyflow/bountyflow-bountyflow-20260929T031500Z.dump | head -30
```

`pg_restore --list` reads the archive's table of contents. If it errors, the file is truncated or corrupt and
the backup is worthless — find out now, not during an incident.

### Targets

| Setting | Value | Why |
|---|---|---|
| Full dump | daily | Bounded restore time; the dataset is small. |
| WAL archiving | continuous | Gets RPO down to minutes (see below). |
| Retention | 30 days of dumps, 14 days of WAL | Long enough to notice slow corruption. |
| Offsite copy | yes | A backup on the database host is not a backup. |
| Restore drill | quarterly | [restore-drill.md](restore-drill.md). |
| RPO / RTO | see [restore-drill.md](restore-drill.md) | Measured, not assumed. |

A dump alone gives an RPO of up to 24 hours. That is not good enough once real money is involved: add WAL
archiving.

### What to back up besides the database

- `.env` — every secret. Store it in the secret manager, never next to the dumps.
- `deploy/audited-deployments.json` — the mainnet guard reads it, and the API will not start on mainnet without
  it.
- `contracts/deployments/*.json` — contract ids, wasm hashes, admin and arbiter addresses.
- The Stellar CLI key store (`~/.config/stellar/identity`) for the deployer, admin and arbiter identities, held
  by their named owners ([secret-rotation.md](secret-rotation.md)).

## WAL archiving and point-in-time recovery

PITR replays the write-ahead log on top of a base backup, so you can stop at any moment instead of at the last
dump. A managed service usually gives you this as a console option with a retention window; configure it and
skip to the drill.

Self-hosted, on the primary:

```ini
# postgresql.conf
wal_level = replica
archive_mode = on
archive_command = 'test ! -f /var/lib/postgresql/wal-archive/%f && cp %p /var/lib/postgresql/wal-archive/%f'
archive_timeout = 300          # force a segment at least every 5 minutes, so the RPO is bounded
```

Take the base backup with `pg_basebackup`, not `pg_dump` — PITR replays WAL onto a physical copy:

```bash
pg_basebackup -h <host> -U <replication role> -D /var/backups/bountyflow/base-20260929 \
  --wal-method=stream --checkpoint=fast --progress
```

To recover to a point in time:

1. Stop PostgreSQL. Move the damaged data directory aside; do not delete it until the recovery is verified.
2. Restore the base backup into the data directory.
3. Point recovery at the archive and the target:

   ```ini
   # postgresql.conf in the restored data directory
   restore_command = 'cp /var/lib/postgresql/wal-archive/%f %p'
   recovery_target_time = '2026-09-29 03:05:00+00'
   recovery_target_action = 'promote'
   ```

4. `touch recovery.signal` in the data directory, then start PostgreSQL. It replays WAL to
   `recovery_target_time` and promotes.
5. Watch the log for `recovery stopping before commit of transaction …` and `database system is ready to accept
   connections`.
6. Verify (below) **before** pointing the API at it.

Choosing the target time: pick the last moment you know the data was good, usually just before the first bad
write. Everything after it is gone. On-chain state is not — the contract still holds whatever it holds, and
reconciliation will pull the escrow view back to chain truth, so err on the side of stopping earlier.

## Restore from a dump

`scripts/restore-db.sh` and `scripts/restore-db.ps1` wrap `pg_restore`. They verify the checksum, refuse a
target database whose name does not match `^bountyflow(_[a-z0-9_]+)?$` unless forced, and make you type the
database name before anything is dropped.

```bash
# Into a scratch database first. Always.
docker compose exec postgres psql -U bountyflow -d postgres -c "CREATE DATABASE bountyflow_restore;"

scripts/restore-db.sh \
  --file /var/backups/bountyflow/bountyflow-bountyflow-20260929T031500Z.dump \
  --docker --database bountyflow_restore
```

```bash
# Against a managed service, with a parallel restore.
scripts/restore-db.sh \
  --file /var/backups/bountyflow/bountyflow-bountyflow-20260929T031500Z.dump \
  --database-url "postgresql://bountyflow:…@db.example.com:5432/bountyflow_restore" \
  --jobs 4
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts/restore-db.ps1 `
  -File .\backups\bountyflow-bountyflow-20260929T031500Z.dump -Docker -Database bountyflow_restore
```

`--force` / `-Force` skips both the prompt and the name check. Use it only in automation, and only where the
target is fixed by the automation itself.

Before restoring over the live database, **stop the writers** so nothing is written into a half-restored schema:

```bash
docker compose stop api worker
# restore…
docker compose start api worker
```

## Verify a restore

Run all four. A restore that has not been verified is a guess.

```bash
# 1. The schema is at the revision the code expects.
docker compose exec -T postgres psql -U bountyflow -d bountyflow_restore -c "SELECT * FROM bountyflow_alembic_version;"

# The same question from the application's side, which is what actually matters at boot:
cd backend && uv run alembic current
```

```sql
-- 2. Row counts for the tables that carry money and identity.
SELECT 'users' AS t, count(*) FROM bountyflow_users
UNION ALL SELECT 'bounties', count(*) FROM bountyflow_bounties
UNION ALL SELECT 'bounty_escrows', count(*) FROM bountyflow_bounty_escrows
UNION ALL SELECT 'blockchain_transactions', count(*) FROM bountyflow_blockchain_transactions
UNION ALL SELECT 'payment_records', count(*) FROM bountyflow_payment_records
UNION ALL SELECT 'wallets', count(*) FROM bountyflow_wallets
UNION ALL SELECT 'outbox_events', count(*) FROM bountyflow_outbox_events
UNION ALL SELECT 'processed_events', count(*) FROM bountyflow_processed_events
UNION ALL SELECT 'audit_logs', count(*) FROM bountyflow_audit_logs
ORDER BY 1;
```

```sql
-- 3. Money adds up the way the CHECK constraint says it must, and nothing is negative.
SELECT count(*) AS broken
FROM bountyflow_bounty_escrows
WHERE paid_out_amount + refunded_amount > funded_amount
   OR funded_amount < 0;
-- Expect 0.

-- 4. Every live escrow still has its on-chain id and contract, so it can be reconciled.
SELECT count(*) AS unreconcilable
FROM bountyflow_bounty_escrows
WHERE state <> 'NOT_CREATED'
  AND (onchain_bounty_id IS NULL OR contract_id IS NULL);
-- Expect 0.
```

Then let the chain settle the rest: start the worker and wait for one `reconciliation-audit` cycle (600 s).
`bountyflow_reconciliation_mismatches` after a PITR restore tells you exactly how much on-chain activity
happened after your recovery target. Reconcile those escrows from the chain
([reconciliation-mismatch.md](reconciliation-mismatch.md)) — the contract is authoritative, so the drift is
recoverable.

What a restore cannot recover: off-chain rows written after the target — submissions, messages, applications,
notifications. Those are gone. Tell the affected users.

## Losing Redis

Redis holds only ephemeral state. Everything in it is namespaced `bountyflow:v1:`.

| What is lost | Effect | Recovers |
|---|---|---|
| Marketplace, bounty, profile and stats caches | A burst of slower first requests. | By itself, on the next request. |
| Rate limit counters | Limits reset; a burst is briefly possible. `rate_limit_unavailable` is logged while Redis is down, and the limiter fails open. | By itself. |
| Wallet ownership challenges (SEP-10 / SEP-53 / SEP-45) | In-flight verifications fail. Challenges fail **closed** without Redis, so nothing is verified unsafely. | The user requests a new challenge. |
| Periodic job locks | While Redis is down, jobs fail closed and are **skipped** rather than run unguarded, so settlement stops. | Automatically when Redis returns. |
| Transaction locks and idempotency keys | A concurrent double submit is no longer caught in Redis. The database's unique and partial-unique indexes and the contract still prevent double effects. | By itself. |
| Worker heartbeats (`bountyflow:v1:worker:heartbeat:*`) | `bountyflow_workers_alive` reads 0 and `BountyFlowNoWorkersAlive` fires even though the worker is fine. | Within ~10 s of Redis returning. |
| The ops snapshots: job health (`bountyflow:v1:ops:jobs`), consumer lag (`bountyflow:v1:ops:kafka-lag`), the last reconciliation audit (`bountyflow:v1:ops:reconciliation`), sanctions list status (`bountyflow:v1:ops:sanctions-list`) | `/metrics` loses those gauges and `/admin/ops/status` comes back mostly empty. Run counters restart from zero. | As each job runs again: seconds for the fast ones, up to 10 minutes for the audit, up to `SANCTIONS_LIST_REFRESH_SECONDS` for the list status. |
| Skill graph cache | Recommendations are slower until the `skill-graph` job runs. | Next run (`DISCOVERY_GRAPH_REFRESH_SECONDS`, 1800 s). |

**No financial state is lost.** Escrows, transactions, payments, sessions, notifications and the outbox all live
in PostgreSQL, and the escrow itself lives on-chain. The compose file runs Redis with `--appendonly yes`, so a
container restart usually keeps the keys anyway; a wiped volume just means everything above rebuilds.

Re-warming, in order:

1. Start Redis, confirm `bountyflow_dependency_up{dependency="redis"}` is 1 and
   `curl -s http://127.0.0.1:8000/health/ready | jq '.checks.redis'` says `ok`.
2. Restart the worker (`docker compose restart worker`) so heartbeats and job health start fresh. Not strictly
   required — it recovers on its own — but it makes the metrics readable immediately.
3. Wait for one `reconciliation-audit` cycle and confirm `bountyflow_reconciliation_mismatches` is 0. A Redis
   outage does not cause drift, but with jobs skipped the sweep was not running either, so check.
4. Confirm `bountyflow_chain_transactions_pending` is draining: the `tx-reconciliation` job was skipped for the
   whole outage, so there may be a small backlog of unverified transactions.
5. Sanctions list status is empty until the next `sanctions-list-refresh` run. Screening itself is unaffected —
   it matches against `bountyflow_screening_entries` in PostgreSQL, not against Redis.

Do not "warm" the caches by hand. They fill on demand and the marketplace uses a generation counter, so there is
nothing to prime.
