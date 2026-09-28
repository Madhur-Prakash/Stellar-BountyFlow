#!/usr/bin/env bash
# Idempotently creates BountyFlow topics and their dead-letter topics.
set -euo pipefail
BOOTSTRAP="${KAFKA_BOOTSTRAP:-kafka:9092}"
PREFIX="${KAFKA_TOPIC_PREFIX:-}"
TOPICS=(bounty.events application.events submission.events payment.events notification.events analytics.events blockchain.events email.events)
for t in "${TOPICS[@]}"; do
  for name in "${PREFIX}${t}" "${PREFIX}${t}.dlq"; do
    /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
      --topic "$name" --partitions 3 --replication-factor 1 >/dev/null
    echo "topic ready: $name"
  done
done
