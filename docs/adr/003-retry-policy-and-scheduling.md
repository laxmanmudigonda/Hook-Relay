# ADR 003: Retry policy and delayed scheduling

## Context

Receivers can fail temporarily through timeouts, connection errors, rate limiting, and server
errors. Retrying immediately can amplify an outage, while sleeping inside a worker wastes capacity
and makes shutdown behavior harder. Retry state also needs to remain inspectable after Redis data
loss.

## Decision

Use a single retry-policy abstraction that classifies transport errors, HTTP 408, 425, 429, and 5xx
responses as retryable. Other 4xx responses are terminal. Retry delay is capped exponential backoff
with full jitter, with a configurable maximum number of total attempts. A valid `Retry-After`
header is treated as a minimum delay but cannot exceed the configured safety cap.

PostgreSQL remains authoritative for delivery status, attempt count, attempt history, and
`next_attempt_at`. Redis uses a sorted set whose score is the due timestamp. Each worker periodically
runs a Lua script that atomically removes a bounded batch of due IDs and appends them to the Redis
Stream. Workers never sleep for an individual delivery.

## Alternatives

- Sleeping inside a worker is simpler but holds worker capacity for every delayed delivery.
- A PostgreSQL polling scheduler avoids duplicate retry state in Redis but adds recurring indexed
  database scans; PostgreSQL remains a possible recovery source later.
- One Redis Stream per delay bucket complicates configuration and gives only coarse timing.
- A separate scheduler service gives clearer ownership at scale, but another process is not needed
  for the current single-developer system.

## Consequences

Retries are bounded, testable, and do not block workers. Jitter spreads load when many receivers
recover together. The sorted set is an operational schedule rather than the system of record.

The PostgreSQL commit and Redis sorted-set write are not atomic. A scheduling failure leaves the
original stream message unacknowledged; an idempotent API retry can republish incomplete work.
Automatic recovery of abandoned pending messages arrives in Phase 7, and the Phase 6 transactional
outbox addresses the earlier PostgreSQL-to-Redis publication gap. Concurrent duplicate processing
and receiver-side duplicates remain possible, consistent with at-least-once delivery.
