# Runbooks

Operational procedures for BountyFlow. Each page is written to be followed under pressure: real commands, real
SQL, real metric names. If something does not exist yet, the page says so rather than inventing it.

## Index

| Runbook | Use it when |
|---|---|
| [incident-response.md](incident-response.md) | Anything is on fire. Severity levels, roles, comms, the post-incident review. |
| [on-call.md](on-call.md) | You are on call. Daily checks, dashboards, alert → first action, escalation, access. |
| [rpc-outage.md](rpc-outage.md) | Soroban RPC or Horizon is unreachable; `502 blockchain_error`; chain actions fail. |
| [reconciliation-mismatch.md](reconciliation-mismatch.md) | The database view of an escrow differs from the contract, or a foreign escrow is detected. |
| [kafka-lag-and-dlq.md](kafka-lag-and-dlq.md) | Consumer lag, dead-letter topics, outbox backlog, dead-lettered outbox rows. |
| [postgres-backup-restore.md](postgres-backup-restore.md) | Backups, point-in-time recovery, restoring, and what losing Redis costs. |
| [restore-drill.md](restore-drill.md) | The quarterly restore drill. |
| [secret-rotation.md](secret-rotation.md) | Rotating any secret, plus the escrow admin key and arbiter key ceremonies. |
| [contract-upgrade.md](contract-upgrade.md) | Upgrading the escrow contract's code, and what the emergency options really are. |
| [deploy-rollback.md](deploy-rollback.md) | Releasing, gating a release, and rolling back code or a migration. |
| [mainnet-launch-checklist.md](mainnet-launch-checklist.md) | Before the first mainnet deployment. |

## Severity

| Severity | Meaning | Examples | Response | Comms |
|---|---|---|---|---|
| SEV1 | Funds are at risk, stuck or unaccounted for, or the platform is down for everyone. | An escrow is frozen with funds in it; a foreign escrow was adopted; payouts confirmed in the database that never happened on-chain; the API is down; PostgreSQL is lost. | Page immediately, 24/7. Incident channel within 5 minutes. | Status page within 30 minutes, updates every 30 minutes. |
| SEV2 | A core flow is broken for many users; no money is at risk. | Funding or payouts cannot be prepared (RPC down); login fails; the worker is not running so nothing settles. | Page during and outside business hours. Incident channel within 15 minutes. | Status page within 60 minutes, updates hourly. |
| SEV3 | A feature is degraded, with a workaround or a bounded blast radius. | Notification emails delayed; Kafka lag; the skill graph is stale; a single bounty is wrong. | Ticket, next business day. | None unless a customer asks. |
| SEV4 | Cosmetic or internal only. | A dashboard panel is empty; a log is noisy; a metrics collector is failing. | Backlog. | None. |

"Funds at risk" is the dividing line. BountyFlow's contract holds real value, and the database is only a mirror
of it. Anything that could make the two disagree about who owns money is SEV1 until proven otherwise.

## Who to page

This deployment has no paging vendor wired up yet. Fill in the rows below before mainnet
([mainnet-launch-checklist.md](mainnet-launch-checklist.md) gates on it) and delete this sentence.

| Role | Who | Reachable via |
|---|---|---|
| Primary on-call | — | — |
| Secondary on-call | — | — |
| Escrow contract admin key holder | — | — |
| Arbiter quorum (M of N) | — | — |
| Database / infrastructure owner | — | — |
| Compliance and legal | — | — |
| Status page and customer comms | — | — |

Alert routing: `severity: page` goes to the primary on-call; `severity: ticket` goes to the team queue. The
severity label is set per alert in [`deploy/prometheus/alerts.yml`](../../deploy/prometheus/alerts.yml).

## First five minutes

1. **Say you have it.** Post in the incident channel: what fired, that you are on it, and the time. Nobody else
   should start debugging the same thing.
2. **Check whether money is involved.** Open the BountyFlow Grafana dashboard and read four numbers:
   `bountyflow_reconciliation_mismatches`, `bountyflow_reconciliation_foreign_escrows`,
   `bountyflow_chain_transaction_oldest_pending_age_seconds`, `bountyflow_escrow_held_amount`. Any mismatch or
   foreign escrow makes this SEV1.
3. **Check what is up.** `bountyflow_dependency_up` per dependency, `bountyflow_workers_alive`, and the API's own
   readiness:

   ```bash
   curl -s http://127.0.0.1:8000/health/ready | jq
   ```

4. **Decide the severity** from the table above and say it out loud in the channel. It is cheap to downgrade
   later and expensive to have started too small.
5. **Open the right runbook** from the index, and keep a timeline as you go — the post-incident review needs it
   and reconstructing it afterwards never works.

Do not restart anything before step 2. A restart can hide the state you need to tell whether funds moved.
