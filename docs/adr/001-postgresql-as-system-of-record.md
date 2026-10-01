# ADR 001: PostgreSQL as the system of record

## Context

Events, delivery state, and attempt history must remain queryable and consistent even when the
queue or a worker is unavailable.

## Decision

Store domain state in PostgreSQL with foreign keys, uniqueness constraints, and Alembic-managed
migrations. Redis transports delivery work but is not the authoritative delivery record.

## Alternatives

- Redis-only state would simplify the first implementation but weaken durability and relational
  querying.
- A document database would fit event payloads but add no benefit for the strongly related delivery
  lifecycle.

## Consequences

Workers must update PostgreSQL before acknowledging queue messages. Database availability remains a
hard dependency, and database-to-queue coordination requires additional reliability work.
