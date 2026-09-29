# Chain versus database drift

The escrow contract is authoritative. `bounty_escrows` is a mirror kept for the UI and for analytics. When they
disagree, the contract is right and the database is wrong — but *how* it is wrong decides what you do, and one
case must never be "fixed" by reconciling.

Start at SEV1 and downgrade once you know what drifted.

## What the metrics mean

The worker's `reconciliation-audit` job runs every 600 seconds. It reads back every escrow the database shows as
live (plus recently terminal ones), compares it with the contract, and writes the result to Redis, which the API
exposes.

| Metric | Meaning |
|---|---|
| `bountyflow_reconciliation_mismatches` | Escrows whose database row differs from the contract on `state`, `funded_amount`, `paid_out_amount` or `refunded_amount`. |
| `bountyflow_reconciliation_foreign_escrows` | Escrow ids occupied by an escrow **BountyFlow did not create**. See below — never reconcile these. |
| `bountyflow_reconciliation_escrows_checked` | How many were compared in the last run (batch limit 200). |
| `bountyflow_reconciliation_last_run_timestamp_seconds` | When it last ran. |
| `bountyflow_reconciliation_last_run_failed` | 1 when the run stopped early because the chain was unreachable. Go to [rpc-outage.md](rpc-outage.md) instead. |

The audit is read only. It never writes to an escrow. It also skips escrows with a transaction still settling —
submitted, or confirmed within the last 3 minutes — because a difference there is expected and closes by itself.

## Read the last audit

```bash
curl -s -b "bf_access=$TOKEN" http://127.0.0.1:8000/api/v1/admin/ops/status | jq '.reconciliation'
```

```json
{
  "at": 1790000000.0,
  "duration_seconds": 4.117,
  "checked": 63,
  "skipped_settling": 2,
  "mismatches": 1,
  "foreign": 0,
  "details": [
    {
      "bounty_id": "…",
      "escrow_id": "6f1d70d9…ba6d",
      "fields": { "paid_out_amount": ["0.0000000", "10.0000000"] }
    }
  ],
  "error": null
}
```

`fields` is `{field: [database, chain]}`. The example says the contract has paid out 10 XLM and the database
still thinks nothing was paid — a missed verification. `details` carries at most 25 entries; the count in
`mismatches` is the real total.

The same snapshot is on the dashboard, and the worker logs one `escrow_reconciliation_mismatch` line per escrow
with the same `fields`.

## Find the suspect escrows in SQL

```sql
-- Live escrows with no settled transaction recently: the ones an audit mismatch is most likely about.
SELECT e.bounty_id,
       b.slug,
       e.onchain_bounty_id,
       e.contract_id,
       e.contract_version,
       e.state,
       e.asset_identifier,
       e.funded_amount,
       e.paid_out_amount,
       e.refunded_amount,
       e.last_reconciled_at,
       e.updated_at
FROM bounty_escrows e
JOIN bounties b ON b.id = e.bounty_id
WHERE e.state IN ('AWAITING_FUNDING', 'FUNDED', 'CANCEL_REQUESTED', 'DISPUTED')
ORDER BY e.last_reconciled_at NULLS FIRST
LIMIT 50;
```

```sql
-- Every chain transaction for one bounty, newest first. Run this before deciding anything.
SELECT id, transaction_type, status, transaction_hash, submitted_at, confirmed_at, failure_reason
FROM blockchain_transactions
WHERE bounty_id = '<bounty uuid>'
ORDER BY created_at DESC;
```

```sql
-- Escrows whose money has moved on-chain but which have no confirmed transaction recorded: the classic
-- "verification was missed" shape.
SELECT e.bounty_id, e.onchain_bounty_id, e.state, e.funded_amount, e.paid_out_amount
FROM bounty_escrows e
WHERE e.state IN ('FUNDED', 'CANCEL_REQUESTED', 'DISPUTED')
  AND NOT EXISTS (
    SELECT 1 FROM blockchain_transactions t
    WHERE t.bounty_id = e.bounty_id AND t.status = 'CONFIRMED'
  );
```

Add `docker compose exec postgres` in front of `psql` for the local stack; against a managed service use
`psql "$DATABASE_URL"` with the `+psycopg` driver suffix removed.

## Read the escrow on-chain

`onchain_bounty_id` is 64 hex characters, and it is **not** derived from the bounty UUID — it is
`sha256("bountyflow:bounty:" || bounty_uuid || random_salt)`, so nobody can pre-create a bounty's escrow. Take
it from the database row, and take the contract from that row too: escrows created on the v1 contract stay on
it.

```bash
ESCROW_ID=6f1d70d9e44f4d49b259e13a78940d3646725b4f440899177d9d3e74cde6ba6d
CONTRACT=CBCXG46FJPYBPWYZ24BWFVNJ6G2ILFAXHX2COETDNXYE6C5IJWAZ3M4C   # bounty_escrows.contract_id

stellar contract invoke --id "$CONTRACT" --source-account bountyflow-deployer --network testnet \
  -- get_escrow --bounty_id "$ESCROW_ID"
```

`get_escrow` is a read: it is simulated and nothing is submitted, so this is safe to run at any time. Two more
reads that help:

```bash
# One contributor's position on the escrow: this is what decides whether a payout really happened.
stellar contract invoke --id "$CONTRACT" --source-account bountyflow-deployer --network testnet \
  -- assignment --bounty_id "$ESCROW_ID" --contributor GABC…

# Which interface the contract speaks (2 = escrow v2).
stellar contract invoke --id "$CONTRACT" --source-account bountyflow-deployer --network testnet -- version
```

`--source-account` only pays for the simulation of a read; any funded identity works.

Compare the contract's `funded_amount`, `paid_out_amount`, `refunded_amount` and status against the database
row. On-chain values are integer stroops; the database stores `NUMERIC(20,7)`. 10 XLM is `100000000` stroops.

## Fix: reconcile from chain

Once you have confirmed the escrow is ours and the contract's numbers are the correct ones:

```bash
curl -s -X POST \
  -b "bf_access=$TOKEN" -H "X-CSRF-Token: $CSRF" \
  http://127.0.0.1:8000/api/v1/admin/bounties/<bounty uuid>/reconcile | jq
```

It needs the `TRANSACTION_VIEW_ALL` permission. It re-reads the escrow from the contract and **overwrites the
database view with verified chain state**, then advances the bounty and payment states that follow from it. It
never writes to the contract and never moves money.

Afterwards:

```sql
SELECT state, funded_amount, paid_out_amount, refunded_amount, last_reconciled_at
FROM bounty_escrows WHERE bounty_id = '<bounty uuid>';
```

and wait for the next audit run (up to 10 minutes) to see `bountyflow_reconciliation_mismatches` drop.

If reconcile answers with a refusal instead of updating, that is the authenticity check doing its job — read
the next section.

## When NOT to reconcile

**A foreign escrow.** `bountyflow_reconciliation_foreign_escrows > 0`, or `foreign_escrow_detected` in the logs.
An escrow exists at one of our ids whose terms do not match any creation we prepared: the audit checks the
snapshot against the `verification_metadata.args` of our own `ESCROW_CREATE` transactions for that bounty.

Reconciling a foreign escrow would adopt someone else's escrow — with their token, their arbiter and their
deadline — and then record payouts against it as if they were real. This is exactly the SEC-01 finding in
[`docs/security.md`](../security.md), and the backend refuses it; the audit flags it so a human looks.

Do this instead:

1. **SEV1.** Do not reconcile. Do not retry funding for that bounty.
2. Read the escrow on-chain with the commands above and record the whole snapshot: token, requester, arbiter set,
   deadline, amounts.
3. Find who created it:

   ```bash
   # The contract's transaction history in the explorer, then look for the create_escrow call carrying this id.
   echo "$STELLAR_EXPLORER_BASE_URL/contract/$CONTRACT"
   ```

4. Check whether any of our transactions touched it:

   ```sql
   SELECT id, transaction_type, status, transaction_hash, created_at
   FROM blockchain_transactions
   WHERE bounty_id = '<bounty uuid>'
   ORDER BY created_at;
   ```

5. Escalate to the backend owner and to whoever owns the contracts. The recovery path is a new escrow id for that
   bounty (the id is salted precisely so a squatted id cannot block funding permanently), not adopting the
   foreign one.

Also do not reconcile when:

- `bountyflow_reconciliation_last_run_failed` is 1 — the chain is unreachable, so reconcile cannot read anything.
  Fix the RPC first ([rpc-outage.md](rpc-outage.md)).
- A transaction for that bounty is still `SUBMITTED`. Let the sweep finish; the audit skips settling escrows for
  the same reason.
- The mismatch is only `state` and the amounts agree, right after a settlement. Wait one audit cycle.

## Escalate

Escalate immediately, without waiting:

- Any foreign escrow.
- A mismatch where the **database shows more paid out than the contract does**. We may have told a contributor
  they were paid when they were not (`payout_not_reflected_on_chain`).
- More than a handful of escrows mismatching at once — that is a systemic bug, not a missed verification, and
  reconciling them one by one hides it.
- Any mismatch that reappears after a successful reconcile. Something is writing the wrong value on every cycle.

Take with you: the `reconciliation` block from `/admin/ops/status`, the `get_escrow` output, the
`blockchain_transactions` rows for the bounty, and the `escrow_reconciliation_mismatch` log lines.
