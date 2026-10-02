# Kafka events

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [Architecture](architecture.md) &middot; [Database](database.md) &middot; [Runbooks](runbooks/README.md)
<!-- nav -->

Domain events are written to the **transactional outbox** (`bountyflow_outbox_events`) in the same database
transaction as the state change. The worker's **outbox relay** publishes them to Kafka. Consumers apply their effects
idempotently.

## Topics

| Topic | Events | Consumers |
|---|---|---|
| `bounty.events` | `qa.question_created`, `qa.reply_created`, `qa.reply_accepted`, `qa.post_hidden`, `bounty.created`, `.updated`, `.published`, `.funding_submitted`, `.funded`, `.status_changed`, `.cancel_requested`, `.cancelled`, `.expired`, `.completed`, `.deadline_approaching`, `.dispute_raised`, `.dispute_updated`, `.dispute_resolved`, `.dispute_vote_recorded` | notification-worker, analytics-worker, discovery-worker |
| `application.events` | `application.created`, `.accepted`, `.rejected`, `.withdrawn` | notification-worker, analytics-worker |
| `submission.events` | `submission.created`, `.resubmitted`, `.revision_requested`, `.approved`, `.rejected`, `.onchain_recorded`, `.claim_available`, `.pull_request_updated` | notification-worker, analytics-worker |
| `payment.events` | `payment.confirmed`, `payment.failed`, `payment.refund_confirmed`, `payment.milestone_confirmed`, `payment.trustline_required`, `attestation.confirmed`, `attestation.revoked` | notification-worker, analytics-worker, reputation-attester |
| `blockchain.events` | `blockchain.transaction_submitted`, `.transaction_confirmed`, `.transaction_failed` | blockchain-verifier, analytics-worker |
| `notification.events` | `notification.created`, `notification.saved_search_alert`, `notification.saved_search_digest` | email-worker |
| `email.events` | `email.verification_requested`, `email.password_reset_requested`, `email.data_export_ready`, `email.account_deletion_requested` | email-worker |
| `analytics.events` | `user.registered`, `user.email_verified`, `wallet.verified`, `wallet.passkey_created`, `github.account_linked`, `github.account_unlinked` | analytics-worker, compliance-worker |
| `<topic>.dlq` | Messages that failed permanently or exhausted retries | Operators (inspect in Kafka UI) |

Topics (3 partitions each) and their DLQs are created by `infra/kafka/create-topics.sh`. Auto-creation is disabled.
The message key is the aggregate ID, which preserves per-aggregate ordering within a partition.

## Envelope

Every message uses the same versioned envelope (`app/messaging/events.py`):

```json
{
  "event_id": "5b1d…",               // UUID, idempotency key
  "event_type": "application.accepted",
  "schema_version": 1,
  "occurred_at": "2026-09-26T10:00:00Z",
  "aggregate_type": "application",
  "aggregate_id": "a3c2…",
  "correlation_id": "c0ff…",         // propagated from the HTTP request that caused it
  "actor_id": "9f1e…",
  "payload": { "application_id": "…", "bounty_id": "…", "requester_id": "…", "contributor_id": "…", "title": "…", "status": "ACCEPTED" }
}
```

Each `event_type` has an explicit payload schema (`app/messaging/schemas.py`). Payloads are validated when they
are written to the outbox and again when consumed. Tokens and secrets are **never** placed in events: the email
worker issues verification and reset tokens itself at send time.

### Escrow v2 events

| Event | When | Payload | Notifications |
|---|---|---|---|
| `submission.onchain_recorded` | A verified `SUBMIT_WORK` started the review clock | the submission payload + `claimable_at` | Requester (`SUBMISSION_RECEIVED`): the review window started, answer before `claimable_at` |
| `submission.claim_available` | The review-clock job found the window passed | the submission payload + `claimable_at` | Contributor and requester (`CLAIM_AVAILABLE`) |
| `payment.milestone_confirmed` | A milestone payout (single, batch leg or claim) was verified on-chain | the payment payload + `milestone_id`, `milestone_title` | Contributor and requester (`MILESTONE_PAID`) |
| `bounty.dispute_vote_recorded` | A verified `DISPUTE_VOTE` | the dispute payload + `approvals`, `threshold` | Both parties (`ARBITER_VOTE`): "2 of 3 arbiter approvals", or that the decision was executed |

### Collaboration events (Q&A and GitHub)

| Event | When | Payload | Notifications |
|---|---|---|---|
| `qa.question_created` | Someone asked a question on a bounty | bounty + `post_id`, `question_id`, `author_id`, `asker_id`, `link` | Requester (`QUESTION_RECEIVED`) |
| `qa.reply_created` | A reply was posted in a thread | the same + `participant_ids`, `is_requester_answer` | The asker and the thread's other participants (`QUESTION_REPLY`); the requester's reply is titled "The requester answered" |
| `qa.reply_accepted` | The requester accepted an answer | the same | The reply's author and the asker (`ANSWER_ACCEPTED`) |
| `qa.post_hidden` | A moderator hid a post | the same | Its author (`SYSTEM`) |
| `submission.pull_request_updated` | A verified re-check found a linked pull request merged or closed | the submission payload + `pull_request_id`, `repository`, `number`, `state`, `previous_state`, `verification` | Contributor and requester (`PULL_REQUEST_UPDATE`) |
| `github.account_linked` / `github.account_unlinked` | A GitHub account was verified or removed | `user_id`, `github_id`, `login` | None (analytics only) |

The Q&A events carry no post body: the notification links to `#q-<question_id>` on the bounty, where the current
text (and whether it is still visible) is read from the database.

## Reliability

| Guarantee | How |
|---|---|
| No lost events | Outbox rows commit with the state change; the relay retries until Kafka acks (`acks=all`, idempotent producer). |
| At-least-once delivery | Consumer offsets are committed only after the handler succeeds or the message is dead-lettered. |
| Idempotent handlers | `processed_events (consumer, event_id)` is inserted in the **same transaction** as the handler's effects, so a redelivered event is skipped. Notifications are also unique per (user, event). Emails are unique per idempotency key. |
| Bounded retries | Exponential backoff with jitter (base 0.5 s, cap 30 s), up to `WORKER_MAX_RETRIES`. After that the message goes to `<topic>.dlq` with `x-error-type`, `x-error-message`, `x-attempts`, `x-permanent`, `x-consumer` and `x-original-*` headers. |
| Malformed messages | Envelope or payload validation failures go to the DLQ immediately; they are never retried. |
| No poison-pill stalls | An outbox row that fails 25 publish attempts is marked dead-lettered with its error kept for inspection. |
| No duplicate payouts | Payouts only happen when a user signs a transaction. Event redelivery re-runs verification, which is idempotent and reads chain state. |
| Graceful shutdown | SIGINT/SIGTERM stop consumers after in-flight messages and flush the producer. The Redis heartbeat key is removed. |

Consumer lag is logged periodically per partition. Consumer groups are named `KAFKA_CONSUMER_GROUP.<consumer>`.

## Without Kafka

With `KAFKA_ENABLED=false`, the relay dispatches events in-process to the same handlers, using the same
idempotency tables. This is useful for minimal local setups and tests.

## Periodic jobs (worker)

| Job | Interval | What it does |
|---|---|---|
| Lifecycle | 60 s | Expires open/funded bounties past their deadline with no contributors; emits `deadline_approaching` 24 h before a completion deadline. |
| Reconciliation | 20 s | Verifies `SUBMITTED` transactions and expires stale unsigned ones. |
| Review clock | 30 s | Finds submissions whose on-chain review window passed unanswered (`claimable_at <= now`, not yet notified), marks them and emits `submission.claim_available` once per submission. |
| Attestation pipeline | 10 s | Signs, submits and verifies queued completion attestations and revocations with the platform attester key. Each step commits before any chain call, so no row lock is held across network I/O. |
| Attestation backfill | 10 min | Queues attestations for completions that have none (payouts settled before the feature was switched on). |
| Attestation reconciliation | 30 min | Re-reads confirmed attestations from the registry contract, flags drift and applies revocations made on-chain elsewhere. |
| Skill graph | 30 min (`DISCOVERY_GRAPH_REFRESH_SECONDS`) | Rebuilds the skill co-occurrence graph from listed bounties and active profiles into `bountyflow_skill_nodes` / `bountyflow_skill_edges`, and caches it in Redis. |
| GitHub pull requests | 30 s | Re-checks linked pull requests that are due, stops re-checking ones on closed submissions, and stages `submission.pull_request_updated` when one becomes merged or closed. Skips the batch entirely while GitHub's rate limit is backing off. |
| Saved-search digests | 5 min | Sends the daily and weekly saved-search digests that are due; each frequency runs in its own transaction. |
| Asset operations | 30 s | Verifies submitted trustline and SAC-deployment transactions. |
| Data exports | 10 s | Builds queued data-export archives and deletes the ones that expired. The archive is read with nothing locked, between the transaction that claims the export and the one that stores it. |
| Account deletion | 5 min | Anonymises accounts whose grace period is over, unless a blocker appeared; the whole anonymisation is one transaction. |
| Sanctions list refresh | 6 h (`SANCTIONS_LIST_REFRESH_SECONDS`) | Syncs screening entries from `SANCTIONS_LIST_PATH` / `SANCTIONS_LIST_URL`. Fails static: an unreadable or suddenly empty source keeps the entries already in place. |
| Reconciliation audit | 10 min | Read-only comparison of every live escrow against the contract; publishes `bountyflow_reconciliation_mismatches` and never writes to an escrow. |

Each job takes a Redis lock (`SET NX EX`), so only one worker replica runs it at a time. The attestation
jobs are no-ops until `ATTESTATION_CONTRACT_ID` and `STELLAR_ATTESTER_SECRET` are configured. Every run a replica
actually performs is recorded for `/metrics` (`bountyflow_worker_job_*`), so a job that stops running is
visible as a stale `last_success` rather than silence.
