# ADR 006: Publish delivery work through a transactional outbox

- Status: Accepted
- Date: 2026-10-01

## Context

Writing a delivery to PostgreSQL and publishing its ID to Redis are two independent operations.
If the API process exits between them, the request can succeed while the durable delivery is never
made visible to a worker. Reversing the order risks publishing work that the database later rolls
back. Distributed transactions would add disproportionate operational complexity.

## Decision

The API writes one `delivery.requested` outbox row for every pending delivery in the same database
transaction as the event or replay state. A separate publisher selects unpublished rows in creation
order with `FOR UPDATE SKIP LOCKED`, appends delivery IDs to the Redis stream, then records
`published_at`. Failures remain unpublished and are retried after the configured polling interval.

Outbox rows are retained as an audit trail. A future retention job may archive or delete old
published rows without affecting correctness.

## Consequences

- A successful API transaction always leaves recoverable publication work in PostgreSQL.
- Redis may be unavailable without making event persistence fail.
- Multiple publisher instances can operate concurrently.
- Delivery remains at-least-once. A publisher crash after Redis accepts `XADD` but before the
  database commit can publish the same delivery again, so consumers must tolerate duplicates.
- Retry timing continues to use the Redis sorted set; abandoned stream entries are addressed by
  worker recovery in Phase 7.
