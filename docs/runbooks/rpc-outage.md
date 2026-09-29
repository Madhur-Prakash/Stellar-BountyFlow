# Soroban RPC or Horizon outage

BountyFlow has no offline or simulated chain mode. Every chain action is a real Stellar transaction, so when the
Soroban RPC is unreachable nothing can be prepared, submitted or verified. Nothing is lost: PostgreSQL is the
source of truth for everything off-chain, and the sweep re-verifies pending transactions once the RPC is back.

Usually SEV2. It becomes SEV1 if a transaction was submitted just before the outage and you cannot tell whether
it landed.

## Symptoms

| Signal | Where |
|---|---|
| `bountyflow_dependency_up{dependency="soroban_rpc"} 0` | `/metrics`, the dashboard's Dependencies panel |
| `502 blockchain_error` on prepare, submit and transaction reads | API responses, client error toasts |
| `"blockchain_rpc": "error"` | `GET /health/ready` (still 200 — the API is deliberately not unhealthy without the RPC) |
| `bountyflow_chain_transactions_pending` climbing, `bountyflow_chain_transaction_oldest_pending_age_seconds` growing | Pending chain transactions panel |
| `bountyflow_reconciliation_last_run_failed 1` | The audit stops early with a `ChainUnavailable` error |
| `reconciliation_audit_chain_unavailable` in the worker logs | Log platform |

Horizon is a separate dependency and is **not** in `bountyflow_dependency_up`. When Horizon is down but the RPC
is up, trustline checks return `UNKNOWN` and nothing is blocked — the simulation and the contract still refuse
whatever cannot succeed, so the only cost is a less friendly error message.

## Verify it is them, not us

```bash
# Soroban RPC health. A healthy node answers {"status":"healthy", ...}; this is exactly what check_rpc() calls.
curl -s -X POST "$STELLAR_SOROBAN_RPC_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}' | jq

# Ledger height, to tell "up but stalled" from "up and current".
curl -s -X POST "$STELLAR_SOROBAN_RPC_URL" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"getLatestLedger"}' | jq

# Horizon root: core_latest_ledger and history_latest_ledger should be close together.
curl -s "$STELLAR_HORIZON_URL/" | jq '{core_latest_ledger, history_latest_ledger, network_passphrase}'
```

From inside the containers, so you test the same network path the API takes:

```bash
docker compose exec api python -c \
  "import asyncio; from app.blockchain.client import check_rpc; print(asyncio.run(check_rpc()))"
```

Then check the provider's status page. If `getHealth` answers from your laptop but not from the container, the
problem is egress, DNS or TLS on the host — not the provider.

A stalled node is worse than a dead one: `getHealth` says healthy while ledgers stop advancing, so verification
silently finds nothing. If `getLatestLedger` is not moving, treat it as down and switch.

## What still works

| Works | Does not work |
|---|---|
| Browsing, searching, applying, submitting work off-chain, Q&A, notifications, email. | `POST /bounties/{id}/chain/prepare` and the `funding/` and `payouts/` aliases. |
| Everything the database owns. It is the source of truth and stays consistent. | `POST /transactions/{id}/submit`. |
| The outbox and Kafka: events keep flowing. | Verification, so nothing moves to `CONFIRMED`. |
| Reads of already-confirmed state. | The `reconciliation-audit` job, which stops early and reports the error. |

**Prepare fails cleanly.** The prepare step simulates the call before anything is recorded, so an unreachable RPC
means no `blockchain_transactions` row is created and no state is changed. There is nothing to clean up
afterwards.

Transactions already `SUBMITTED` are the only real exposure: they may have landed on-chain while we cannot read
the result. They are not lost — see the sweep below.

## Switch to a fallback provider

`STELLAR_SOROBAN_RPC_URL` and `STELLAR_HORIZON_URL` are plain configuration. Both the API and the worker read
them at startup, so both must be restarted.

1. Pick a fallback endpoint on the **same network**. A mainnet deployment refuses any URL that is not https and
   refuses one containing `testnet` (`app/core/mainnet.py`).
2. Edit `.env`:

   ```bash
   STELLAR_SOROBAN_RPC_URL=https://<fallback-rpc-host>
   STELLAR_HORIZON_URL=https://<fallback-horizon-host>
   ```

3. Restart the two processes that talk to the chain:

   ```bash
   docker compose restart api worker
   ```

4. Confirm the new endpoint is being used and is healthy:

   ```bash
   curl -s http://127.0.0.1:8000/api/v1/config/public | jq '{network, soroban_rpc_url, horizon_url}'
   curl -s http://127.0.0.1:8000/health/ready | jq
   ```

   `GET /config/public` is public and reports the network and endpoints the API is actually running with. If the
   passphrase or network looks wrong, stop: a transaction prepared for one network cannot be submitted to
   another, and the API refuses it.

Do not change `STELLAR_NETWORK_PASSPHRASE` while switching providers. Changing it changes what the deployment
believes it is connected to, and mismatched configuration is refused at startup.

## After the RPC is back: the drain

Nothing needs to be replayed by hand. Two mechanisms catch up on their own.

**The sweep.** The worker's `tx-reconciliation` job runs every 20 seconds and re-verifies `SUBMITTED`
transactions in batches of 50 (`sweep_pending_transactions`). Verification is idempotent: it calls
`getTransaction`, and treats `NOT_FOUND` as still pending until the transaction's expiry plus a grace period.
After `SUCCESS` it reads `get_escrow` (and `assignment` for payouts) from the contract and overwrites the
database escrow view with chain truth — only then do bounty and payment states advance. A transaction that
expired without inclusion becomes `EXPIRED`, the bounty or payment reverts, and the user re-prepares.

Watch it drain:

```promql
bountyflow_chain_transactions_pending
bountyflow_chain_transaction_oldest_pending_age_seconds
```

```sql
-- Oldest still-unverified submissions. This should shrink within a few minutes of the RPC returning.
SELECT transaction_type, count(*), min(submitted_at) AS oldest
FROM blockchain_transactions
WHERE status = 'SUBMITTED'
GROUP BY transaction_type
ORDER BY oldest;
```

**The audit.** `reconciliation-audit` runs every 600 seconds and compares every live escrow with the contract.
After a long outage, wait for one clean run and check `bountyflow_reconciliation_mismatches` and
`bountyflow_reconciliation_foreign_escrows` are both 0 before you call the incident resolved. If either is not
zero, go to [reconciliation-mismatch.md](reconciliation-mismatch.md) — do not reconcile anything on a hunch.

Also confirm the outbox drained: an RPC outage does not stall the relay, but a worker restart during the outage
can leave a backlog. See [kafka-lag-and-dlq.md](kafka-lag-and-dlq.md).

## What not to do

- **Do not mark transactions `FAILED` by hand.** Only verification against the chain may decide that. A row you
  fail by hand can be a payout that actually happened.
- **Do not run `POST /admin/bounties/{id}/reconcile` during the outage.** It reads the contract; with no RPC it
  cannot, and it is the wrong tool for an outage anyway.
- **Do not switch networks.** Never point a deployment at a different Stellar network to "get it working".
- **Do not clear `blockchain_transactions` rows.** They are never deleted; failures keep their `failure_reason`.
