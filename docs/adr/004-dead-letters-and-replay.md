# ADR 004: Dead letters and manual replay

## Context

Retryable deliveries need a visible terminal state after exhausting their automatic retry budget.
Operators also need a deliberate way to try the delivery again after repairing the receiver,
without erasing the evidence needed to understand the original failure.

## Decision

Mark retryable failures as `dead_lettered` when the retry policy reports attempt exhaustion.
Non-retryable failures remain `failed` because they did not pass through retry exhaustion.

Manual replay is exposed as `POST /api/v1/deliveries/{id}/replay` and is allowed only for a
dead-lettered delivery whose endpoint is enabled. It reuses the same delivery and event, resets
`current_attempt_count` to zero, increments `replay_count`, records `last_replayed_at`, changes the
status to `pending`, and publishes the delivery ID to the existing Redis Stream.

`attempt_count` and `DeliveryAttempt.attempt_number` are lifetime values and never reset. A replay
therefore preserves a single ordered audit history while receiving a fresh automatic retry budget.
A row lock serializes competing replay requests so only one can transition a dead letter.

## Alternatives

- Creating a new delivery per replay gives each run a clean row but fragments history and conflicts
  with the existing event/endpoint uniqueness constraint.
- Resetting the lifetime attempt count makes the retry implementation simpler but would require
  deleting or renumbering historical attempts.
- Automatically replaying all dead letters after a delay removes operator control and can restart
  traffic to a receiver that is still broken.
- Replaying any terminal state is flexible but risks duplicating already successful deliveries or
  repeatedly sending requests known to be invalid.

## Consequences

Operators can distinguish immediate permanent failures from exhausted transient failures and can
recover a dead letter without losing history. The lifetime and current-cycle counters have distinct
meanings that clients must understand.

The PostgreSQL replay commit and Redis publication are not atomic. A publication failure returns
HTTP 503 after persisting `pending`; the original idempotent event request can republish that work.
Phase 6 will route publication through the transactional outbox. At-least-once semantics still
permit receiver-side duplicates, so replay is an explicit operation rather than an exactly-once
guarantee.
