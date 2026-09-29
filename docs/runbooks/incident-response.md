# Incident response

How BountyFlow runs an incident: what counts as which severity, who does what, how fast we say something, and
what we write down afterwards.

## Severity levels

BountyFlow holds real value in a Soroban contract and mirrors it in PostgreSQL. Severity follows the money.

### SEV1 — funds at risk, or the platform is down

Page immediately, any hour. Incident channel within 5 minutes, status page within 30.

| Example | Why it is SEV1 |
|---|---|
| Funds stuck in escrow: an escrow reads `Disputed` or `CancelRequested` on-chain and no path out is working. | Somebody's money is frozen and they cannot get it. |
| `bountyflow_reconciliation_foreign_escrows > 0`. | An escrow at one of our ids was not created by us. Adopting it would let an attacker choose the token, arbiter or deadline. |
| `bountyflow_reconciliation_mismatches` growing, especially on `funded_amount` or `paid_out_amount`. | The database says a different thing about money than the contract does. |
| A payout shows `CONFIRMED` in the database but the contract does not read the position as `Paid` (`payout_not_reflected_on_chain` in the logs). | We told a contributor they were paid and they were not. |
| PostgreSQL is lost or corrupt. | The source of truth for everything off-chain. |
| The API is returning 5xx for everyone. | Nobody can do anything. |
| A `contract_upgraded` event nobody planned. | The escrow admin key has been used. Treat as a key compromise. |
| The sponsor account is drained far faster than `SPONSOR_DAILY_FEE_LIMIT_STROOPS` should allow. | Either the caps are not being enforced or the sponsor key leaked. |

### SEV2 — a core flow is broken, no money at risk

Page during and outside business hours. Incident channel within 15 minutes, status page within 60.

| Example | Why it is SEV2 |
|---|---|
| Soroban RPC is down: prepare and submit answer `502 blockchain_error`. | Nothing can be funded or paid out, but nothing is lost and the DB stays consistent. See [rpc-outage.md](rpc-outage.md). |
| No worker has a heartbeat (`bountyflow_workers_alive == 0`). | Nothing relays the outbox, verifies transactions or runs periodic jobs. Submitted transactions stay unverified. |
| Login or registration is failing. | Existing sessions keep working; new ones do not. |
| Redis is down. | Rate limits, wallet challenges and job locks are gone; periodic jobs fail closed and stop running. |
| `bountyflow_outbox_oldest_unpublished_age_seconds > 900`. | Every downstream effect is stalled. Nothing is lost. |

### SEV3 — degraded, with a workaround

Ticket for the next business day.

Notification emails delayed by Kafka lag; the skill graph or saved-search digests stale; one bounty in a wrong
state; a data export failing; GitHub pull request re-checks backing off on the rate limit.

### SEV4 — cosmetic or internal

Backlog. An empty dashboard panel, a noisy log, one failing metrics collector, a flapping alert threshold.

## Roles

For a SEV1 or SEV2 name all three at the start, even if the same person holds two of them. Say the names in the
channel.

| Role | Owns | Does not do |
|---|---|---|
| Incident commander (IC) | The decision, the severity, the timeline, who does what next. | Debugging. The IC's hands stay off the keyboard. |
| Comms | The status page, customer replies, internal updates on the clock. | Deciding anything technical. |
| Ops | The actual investigation and the changes. | Answering customers or updating the status page. |

Rules that matter:

- **One person changes things at a time**, and says what they are about to do before doing it.
- **The IC can always escalate.** Waking a second person is cheaper than a wrong call on money.
- **Hand over explicitly.** "I am handing IC to X at 14:05" in the channel, or it did not happen.

## Timeline expectations

| Severity | Acknowledge | Incident channel | First status page | Update cadence | Review due |
|---|---|---|---|---|---|
| SEV1 | 5 min | 5 min | 30 min | every 30 min | 3 business days |
| SEV2 | 15 min | 15 min | 60 min | hourly | 5 business days |
| SEV3 | next business day | not required | not required | on request | not required |
| SEV4 | backlog | no | no | no | no |

Keep a running timeline in the channel with timestamps: what fired, what was checked, what was changed, what the
effect was. Never reconstruct it later.

## Comms templates

### Internal, opening a SEV1 or SEV2

```text
SEV1 — funds stuck in escrow on bounty <ref>
Started: 2026-09-29 03:12 UTC (alert BountyFlowForeignEscrow)
IC: <name> · Comms: <name> · Ops: <name>
Impact: <who cannot do what; how many bounties/users; how much value>
Status: investigating
Next update: 03:45 UTC
```

### Internal update

```text
SEV1 update 03:45 UTC
Found: <one sentence>
Doing: <one sentence>
Impact unchanged / now <…>
Next update: 04:15 UTC
```

### Resolution

```text
SEV1 resolved 05:20 UTC (2h 08m)
Cause: <one sentence>
Fix: <one sentence>
Follow-up: <ticket links>
Review: <owner>, due <date>
```

## Status page wording

Plain, specific, no speculation about cause and no blame. Say what a user can and cannot do right now.

**Investigating (SEV1, funds affected)**

> We are investigating a problem affecting escrowed funds on some bounties. Funding and payouts may fail or show
> the wrong state. No action is needed from you. Next update in 30 minutes.

**Investigating (SEV2, chain unavailable)**

> Funding and payouts are currently failing because our Stellar network provider is unreachable. Bounties,
> applications and submissions are unaffected, and nothing that was already on-chain has changed. Next update in
> one hour.

**Identified**

> We have identified the cause and are applying a fix. Funding and payouts are still unavailable. Next update in
> 30 minutes.

**Monitoring**

> The fix is in place and funding and payouts are working again. We are monitoring before we close this out.

**Resolved**

> This is resolved. Between 03:12 and 05:20 UTC funding and payouts failed for some bounties. No funds were lost
> or moved incorrectly. If a bounty still looks wrong, contact support with the bounty link.

Never write "no data was affected" or "no funds were lost" until reconciliation confirms it. Say "we are
confirming" instead.

## Post-incident review

Blameless. Due within the window in the table above. One page, no more.

```markdown
# <SEV_> <short title> — <date>

## Summary
Two or three sentences: what broke, who it affected, how long, how it ended.

## Impact
- Users affected: <count / which flows>
- Value affected: <amount and asset, or "none">
- Duration: <detection to resolution>
- Data: <anything lost, anything inconsistent, how it was made consistent>

## Timeline (UTC)
| Time | Event |
|---|---|
| 03:12 | BountyFlowForeignEscrow fired |
| 03:14 | Acknowledged, SEV1 declared, IC <name> |
| … | … |

## What happened
The mechanism, in order. Contributing factors, not "root cause" — there is usually more than one.

## Detection
What told us, and how long after it started. Would an existing alert have caught it sooner? Did we find it from
a customer report?

## What went well
## What was hard
## Where we got lucky

## Actions
| # | Action | Type (prevent / detect / mitigate) | Owner | Due |
|---|---|---|---|---|
| 1 | | | | |

## Open questions
```

An action without an owner and a date is not an action. If the review produces no detection action, ask again
whether the alerting was really adequate.
