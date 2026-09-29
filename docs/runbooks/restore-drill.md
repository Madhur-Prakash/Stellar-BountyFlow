# Restore drill

A backup that has never been restored is a hypothesis. Once a quarter, someone who is not the person who set up
the backups restores one end to end, from the artefacts alone, and writes down how long each step took.

## Goals

- Prove the latest backup restores into a working database.
- Measure the real RTO and RPO, rather than the ones in the design doc.
- Make sure someone other than the usual person can do it, from this page and the artefacts.
- Find the gaps while nothing is on fire: a missing credential, a stale runbook step, a pruned WAL segment.

## Targets

| Measure | Target | How it is measured in the drill |
|---|---|---|
| RTO — restore to a verified, serving database | 2 hours | From "start the drill" to the last verification query passing. |
| RPO — data loss with daily dumps only | 24 hours | Age of the newest usable dump. |
| RPO — with WAL archiving | 5 minutes | `archive_timeout` on the primary; confirm the newest archived segment. |
| Time to find and verify a backup | 15 minutes | Step 1 below. |
| Time to restore into a scratch database | 45 minutes | Step 3. |

If a measured time is worse than the target, that is a finding, not a failed drill. Record it and raise a ticket.

## Ground rules

- **Never against production.** Restore into a scratch database (`bountyflow_restore_<date>`) or a throwaway
  host. The restore scripts refuse a database whose name does not match `^bountyflow(_[a-z0-9_]+)?$` anyway.
- **No shortcuts.** Use only this page, [postgres-backup-restore.md](postgres-backup-restore.md), and the backup
  artefacts. If you need something that is not there, that is the finding.
- **Time every step.** Write the wall-clock time as you go.
- **The driver is not the backup owner.** Rotate who runs it.

## Steps

### 1. Find and verify a backup (target: 15 min)

```bash
ls -lt /var/backups/bountyflow/*.dump | head -5
sha256sum -c /var/backups/bountyflow/<newest>.dump.sha256
pg_restore --list /var/backups/bountyflow/<newest>.dump | head -30
```

Record: the file, its timestamp, its size, and whether the checksum verified. Also note the newest archived WAL
segment, because that is the real RPO.

### 2. Prepare the target (target: 5 min)

```bash
docker compose exec postgres psql -U bountyflow -d postgres \
  -c "CREATE DATABASE bountyflow_restore_20260929;"
```

Managed service: create a scratch database on a non-production instance, or restore to a new instance from the
provider's snapshot.

### 3. Restore (target: 45 min)

```bash
scripts/restore-db.sh \
  --file /var/backups/bountyflow/<newest>.dump \
  --docker --database bountyflow_restore_20260929
```

Record the start and end time and any error, including ones the restore recovered from.

### 4. Point-in-time recovery (once a year, or after any change to WAL archiving)

Follow the PITR section of [postgres-backup-restore.md](postgres-backup-restore.md) with
`recovery_target_time` set to about an hour ago. Record how long replay took and whether the archive had every
segment it needed. A gap in the archive is the single most common reason PITR fails when it matters.

### 5. Verify (target: 20 min)

Run every query in the verification section of
[postgres-backup-restore.md](postgres-backup-restore.md) against the restored database, and record the results:

- `alembic_version` matches the revision the deployed code expects.
- Row counts for `users`, `bounties`, `bounty_escrows`, `blockchain_transactions`, `payment_records`, `wallets`,
  `outbox_events`, `processed_events`, `audit_logs`.
- The money invariant (`paid_out_amount + refunded_amount > funded_amount`) returns 0.
- Every live escrow still has `onchain_bounty_id` and `contract_id`.

Then run the application against it. This is the part people skip and it is the part that finds real problems:

```bash
# A throwaway API process pointed at the restored database. Never start a worker against a scratch database:
# it would relay outbox rows and re-send real notifications and emails.
cd backend
DATABASE_URL="postgresql+psycopg://bountyflow:…@127.0.0.1:5432/bountyflow_restore_20260929" \
  RUN_MIGRATIONS_ON_STARTUP=false SEED_ON_STARTUP=false KAFKA_ENABLED=false \
  uv run alembic current

# Optional: start the API on another port and read a bounty and a profile through it.
```

Also compare a handful of escrows against the chain by hand, using the `get_escrow` command in
[reconciliation-mismatch.md](reconciliation-mismatch.md), and confirm the contract agrees with the restored
rows.

### 6. Clean up

```bash
docker compose exec postgres psql -U bountyflow -d postgres \
  -c "DROP DATABASE bountyflow_restore_20260929 WITH (FORCE);"
```

Delete any scratch host. Never leave a restored copy of user data lying around — it is the same personal data,
with none of the production controls.

## Verification checklist

- [ ] The newest backup was found from the runbook alone, with no tribal knowledge.
- [ ] Its checksum verified.
- [ ] `pg_restore --list` read the archive.
- [ ] The restore completed with no errors.
- [ ] `alembic current` matches the deployed revision.
- [ ] Row counts are in line with production (within the backup's age).
- [ ] The money invariant query returned 0.
- [ ] Every live escrow has an `onchain_bounty_id` and a `contract_id`.
- [ ] A sample of escrows matches the contract on-chain.
- [ ] PITR replayed to the chosen target (annual, or after any WAL change).
- [ ] The scratch database and any scratch host were destroyed.
- [ ] Every timing was recorded, and every gap raised as a ticket with an owner.

## Record template

Fill this in and keep it with the operational records.

```markdown
# Restore drill — <YYYY-QN>

Date: <date>
Driver: <name>   Observer: <name>
Backup used: <filename> (taken <timestamp>, <size>)
Newest archived WAL segment at start: <name / timestamp>
Target: <scratch database or host>

## Timings
| Step | Target | Actual | Notes |
|---|---|---|---|
| Find and verify the backup | 15 min | | |
| Prepare the target | 5 min | | |
| Restore | 45 min | | |
| PITR replay (if run) | — | | |
| Verify | 20 min | | |
| **Total (RTO)** | **2 h** | | |

## Measured RPO
Newest usable dump: <timestamp>  → <N> hours
Newest archived WAL: <timestamp> → <N> minutes

## Verification results
| Check | Result |
|---|---|
| Checksum | |
| pg_restore --list | |
| alembic current | |
| Row counts | |
| Money invariant | 0 / <n> |
| Escrow ids present | 0 / <n> |
| On-chain sample matches | |

## Findings
| # | Finding | Severity | Owner | Ticket | Due |
|---|---|---|---|---|---|
| 1 | | | | | |

## Changes to make
- Runbook: <what was wrong or missing>
- Backups: <retention, schedule, archiving>
- Access: <who could not get what>

Signed off: <name>, <date>
```
