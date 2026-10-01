# ADR 002: Redis Streams for background delivery

## Context

Webhook receiver latency and availability must not hold open event-ingestion requests. Workers also
need consumer groups, explicit acknowledgement, and visible pending messages.

## Decision

Publish delivery IDs to a Redis Stream and consume them through one consumer group. A worker writes
the delivery result and attempt to PostgreSQL before acknowledging the stream entry.

## Alternatives

- FastAPI background tasks do not survive process crashes and provide no shared backlog.
- A PostgreSQL polling queue avoids another dependency but does not demonstrate Redis consumer-group
  semantics targeted by this project.
- Kafka and RabbitMQ add unjustified operational scope at the current scale.

## Consequences

The API no longer waits for receiver HTTP calls. Delivery is duplicate-tolerant, not exactly once.
A crash between the PostgreSQL commit and Redis publication can still strand pending work until the
transactional outbox is added. Abandoned pending entries are not reclaimed until Phase 7.
