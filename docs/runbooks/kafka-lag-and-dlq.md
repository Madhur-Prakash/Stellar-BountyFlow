# Kafka lag, DLQ replay and the outbox

Domain events are written to `bountyflow_outbox_events` in the same transaction as the state change. The worker's
outbox relay publishes them to Kafka. Consumers apply their effects and deduplicate on `bountyflow_processed_events`.

Two different backlogs, with different causes and different fixes:

| Backlog | Metric | Means |
|---|---|---|
| Outbox | `bountyflow_outbox_backlog` | Events are committed but not published. The **relay** is stuck (worker down, Kafka unreachable). |
| Consumer lag | `bountyflow_kafka_consumer_lag{consumer}` | Events are in Kafka but a consumer is not keeping up or is crash-looping. |

Neither loses data. Both delay effects: notifications, emails, analytics, chain verification and attestations.
Usually SEV3, SEV2 when the relay is stalled outright.

## Topics and consumers

Topics (3 partitions each) and their `.dlq` siblings are created by `infra/kafka/create-topics.sh`;
auto-creation is disabled. Consumer groups are named `KAFKA_CONSUMER_GROUP.<consumer>`, so with the default
`bountyflow-workers` the notification worker's group is `bountyflow-workers.notification-worker`.

| Consumer | Topics |
|---|---|
| `notification-worker` | `bounty.events`, `application.events`, `submission.events`, `payment.events` |
| `email-worker` | `notification.events`, `email.events` |
| `analytics-worker` | `bounty.events`, `application.events`, `submission.events`, `payment.events`, `analytics.events`, `blockchain.events` |
| `blockchain-verifier` | `blockchain.events` |
| `reputation-attester` | `payment.events` |
| `discovery-worker` | `bounty.events` |
| `compliance-worker` | `analytics.events` |

`KAFKA_TOPIC_PREFIX` is prepended to every topic name when it is set. The commands below assume it is empty.

## Inspect lag

The metric comes from the worker, which writes its own reading to Redis about once a minute. Confirm it against
Kafka before acting — `bountyflow_kafka_consumer_lag_age_seconds` tells you how old the reading is.

```bash
# One group.
docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 \
  --describe --group bountyflow-workers.notification-worker

# Every group at once.
docker compose exec kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server kafka:9092 --describe --all-groups
```

Read the output this way:

| Column | What it tells you |
|---|---|
| `LAG` per partition | Where the backlog is. Lag on one partition only usually means one poison key, not a slow consumer. |
| `CONSUMER-ID` empty | Nobody is consuming that partition. The worker is down or crash-looping. |
| `CURRENT-OFFSET` not moving between two runs | The consumer is stuck on one message. |

Managed Kafka: use the provider's console or the same `kafka-consumer-groups.sh` from a client host with
`--bootstrap-server <broker>:9093 --command-config <client.properties>`.

`kafka-ui` is available locally for browsing topics and messages:

```bash
docker compose --profile tools up -d kafka-ui   # http://127.0.0.1:8080
```

## Read a dead-letter topic

A message goes to `<topic>.dlq` when the handler exhausted `WORKER_MAX_RETRIES` (exponential backoff with
jitter, base 0.5 s, cap 30 s), or immediately when the envelope or payload fails validation — malformed messages
are never retried.

```bash
docker compose exec kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 \
  --topic payment.events.dlq \
  --from-beginning --max-messages 20 \
  --property print.headers=true \
  --property print.key=true \
  --property print.timestamp=true
```

The headers the consumer writes (`worker/retry.py`, `dlq_headers`):

| Header | Meaning |
|---|---|
| `x-consumer` | Which consumer gave up. |
| `x-original-topic` | The topic it came from, prefix included. |
| `x-original-partition`, `x-original-offset` | Where it was, so you can find it again in the source topic. |
| `x-error-type` | The exception class name. |
| `x-error-message` | The message, truncated to 1000 characters. |
| `x-attempts` | How many times the handler ran. |
| `x-permanent` | `true` when the error was classified as permanent — a retry will fail the same way. |

The value is the original event envelope as JSON, or `{"raw": "…"}` when it could not be parsed at all.

> `docs/kafka-events.md` describes these as `x-error` / `x-attempts` / `x-original-*`. The code emits
> `x-error-type` and `x-error-message`, not a single `x-error`. Use the names in the table.

Sort what you find into three piles:

1. **Permanent and our bug** (`x-permanent: true`, a `ValidationFailed` or a `KeyError`). Fix the code, deploy,
   then replay.
2. **Transient that outlasted the retries** (a timeout, a connection error). Replay once the dependency is back.
3. **Malformed** (`{"raw": …}`, or an envelope that fails validation). Do not replay. It will fail identically.
   Keep it for the review.

## Replay from a DLQ

Replay means producing the message back to the topic it came from. This is safe: `process_event` inserts
`processed_events (consumer, event_id)` in the **same transaction** as the handler's effects, so an event that
already succeeded is skipped, and notifications are additionally unique per `(user, source_event_id)` and emails
per idempotency key.

Check first whether the effect already happened:

```sql
-- Did any consumer already process this event_id?
SELECT consumer, created_at FROM bountyflow_processed_events WHERE event_id = '<event_id from the envelope>';
```

Then replay. Produce the **envelope**, one JSON object per line, with the aggregate id as the key so partition
ordering is preserved:

```bash
# Capture the DLQ payloads you want, one JSON object per line, into replay.ndjson first, then:
docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server kafka:9092 \
  --topic payment.events \
  --property "parse.key=true" \
  --property "key.separator=\t" \
  < replay.ndjson
```

Each line must be `<aggregate_id>\t<envelope JSON>`. The aggregate id is `aggregate_id` in the envelope; using
anything else breaks per-aggregate ordering within a partition.

Rules:

- **Replay into the origin topic, not the DLQ.** Consumers do not subscribe to `.dlq` topics.
- **Replay a few first.** Confirm they are consumed and the effect landed before doing the rest.
- **Never edit the envelope.** `event_id` is the idempotency key; changing it turns a replay into a duplicate.
- **Do not replay malformed messages.** They fail validation again and land straight back in the DLQ.

Nothing removes messages from a DLQ topic — it ages out by retention. That is deliberate: the DLQ is the record.

## The outbox's own dead-lettering

The relay is separate from the Kafka DLQ and has its own safety valve. When publishing one row fails 25 times
(`OUTBOX_MAX_ATTEMPTS` in `app/modules/ops/collectors.py`, `max_attempts` in `relay_batch`), the relay sets
`published_at` and stops retrying, keeping `last_error`, so one poison event cannot block the queue forever. The
event was **not** published: its effects never happened.

`bountyflow_outbox_dead_lettered_events` counts rows with `published_at IS NOT NULL AND retry_count >= 25`. It
should always be zero. The log line is `outbox_event_dead_lettered`.

```sql
-- What was given up on, and why.
SELECT id, topic, event_type, aggregate_type, aggregate_id, retry_count, created_at, published_at, last_error
FROM bountyflow_outbox_events
WHERE published_at IS NOT NULL AND retry_count >= 25
ORDER BY created_at
LIMIT 50;
```

```sql
-- Group the errors: one shared cause is much more likely than 30 unrelated ones.
SELECT left(last_error, 120) AS error, count(*)
FROM bountyflow_outbox_events
WHERE published_at IS NOT NULL AND retry_count >= 25
GROUP BY 1 ORDER BY 2 DESC;
```

**Requeue** only after the cause is fixed. Clearing `published_at` puts the row back in the relay's queue and
resetting `retry_count` gives it a fresh 25 attempts:

```sql
-- One row, by id. Prefer this.
UPDATE bountyflow_outbox_events
SET published_at = NULL, retry_count = 0
WHERE id = '<outbox event uuid>';

-- A whole batch that shared one cause. Read them with the SELECT above first.
UPDATE bountyflow_outbox_events
SET published_at = NULL, retry_count = 0
WHERE published_at IS NOT NULL
  AND retry_count >= 25
  AND last_error LIKE '%<the error you fixed>%';
```

Requeuing is safe for the same reason replay is: consumers deduplicate on `processed_events (consumer,
event_id)`, and the envelope in `payload` keeps its original `event_id`.

Watch it drain:

```promql
bountyflow_outbox_backlog
bountyflow_outbox_dead_lettered_events
bountyflow_outbox_oldest_unpublished_age_seconds
```

## A stalled relay

`bountyflow_outbox_oldest_unpublished_age_seconds` climbing while `bountyflow_outbox_dead_lettered_events` stays
at zero means the relay is not running or cannot publish at all.

1. Is the worker alive? `bountyflow_workers_alive`, then `docker compose ps worker`.
2. Is Kafka up? `bountyflow_dependency_up{dependency="kafka"}`, then
   `curl -s http://127.0.0.1:8000/health/ready | jq '.checks.kafka'`.
3. Worker logs: `outbox_relay_failed` carries the error and the backoff; `kafka_producer_unavailable` means the
   producer cannot even start.
4. Restart the worker: `docker compose restart worker`. Restarting is safe — rows stay unpublished and are
   retried, and in-flight Kafka messages are redelivered and deduplicated.

The relay polls every `OUTBOX_POLL_INTERVAL_SECONDS` (1 s) in batches of `OUTBOX_BATCH_SIZE` (100), and when it
publishes a full batch it immediately fetches the next one. It uses `SELECT … FOR UPDATE SKIP LOCKED`, so
several relay instances are safe.

## Fallback: run without Kafka

`KAFKA_ENABLED=false` makes the relay dispatch events in-process to the same handlers, with the same idempotency
tables. It is a real fallback, and it is how minimal local setups run.

```bash
# In .env
KAFKA_ENABLED=false
```

```bash
docker compose restart api worker
```

What you give up:

- **No DLQ topic.** An event that exhausts its retries is logged as `event_dead_lettered` with
  `dispatch=in_process` and is otherwise dropped. There is nothing to replay from.
- **No parallelism across replicas.** Dispatch happens inside the relay loop, so a slow handler slows the relay.
  In-process retries are capped at 2 s of backoff for exactly this reason.
- **No consumer lag metric.** `bountyflow_kafka_consumer_lag` has no series, so its alerts cannot fire.

Turning it back on: set `KAFKA_ENABLED=true`, make sure the topics exist (`docker compose up kafka-init`), and
restart the API and the worker. Events written while Kafka was off were already dispatched in-process — they are
marked published and are not re-sent.
