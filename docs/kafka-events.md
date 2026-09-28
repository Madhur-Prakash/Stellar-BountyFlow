# Kafka events

Domain events are written to the **transactional outbox** (`outbox_events`) in the same database transaction as
the state change. The worker's **outbox relay** publishes them to Kafka. Consumers apply their effects
idempotently.

## Topics

| Topic | Events | Consumers |
|---|---|---|
| `bounty.events` | `bounty.created`, `.updated`, `.published`, `.funding_submitted`, `.funded`, `.status_changed`, `.cancel_requested`, `.cancelled`, `.expired`, `.completed`, `.deadline_approaching`, `.dispute_raised`, `.dispute_updated`, `.dispute_resolved` | notification-worker, analytics-worker |
| `application.events` | `application.created`, `.accepted`, `.rejected`, `.withdrawn` | notification-worker, analytics-worker |
| `submission.events` | `submission.created`, `.resubmitted`, `.revision_requested`, `.approved`, `.rejected` | notification-worker, analytics-worker |
| `payment.events` | `payment.confirmed`, `payment.failed`, `payment.refund_confirmed` | notification-worker, analytics-worker |
| `blockchain.events` | `blockchain.transaction_submitted`, `.transaction_confirmed`, `.transaction_failed` | blockchain-verifier, analytics-worker |
| `notification.events` | `notification.created` | email-worker |
| `email.events` | `email.verification_requested`, `email.password_reset_requested` | email-worker |
| `analytics.events` | `user.registered`, `user.email_verified`, `wallet.verified` | analytics-worker |
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

## Reliability

| Guarantee | How |
|---|---|
| No lost events | Outbox rows commit with the state change; the relay retries until Kafka acks (`acks=all`, idempotent producer). |
| At-least-once delivery | Consumer offsets are committed only after the handler succeeds or the message is dead-lettered. |
| Idempotent handlers | `processed_events (consumer, event_id)` is inserted in the **same transaction** as the handler's effects, so a redelivered event is skipped. Notifications are also unique per (user, event). Emails are unique per idempotency key. |
| Bounded retries | Exponential backoff with jitter (base 0.5 s, cap 30 s), up to `WORKER_MAX_RETRIES`. After that the message goes to `<topic>.dlq` with `x-error`, `x-attempts` and `x-original-*` headers. |
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

Each job takes a Redis lock (`SET NX EX`), so only one worker replica runs it at a time.
