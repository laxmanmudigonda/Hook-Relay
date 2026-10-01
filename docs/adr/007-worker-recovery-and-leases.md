# ADR 007: Recover abandoned work with Redis claims and database leases

- Status: Accepted
- Date: 2026-10-01

## Context

Redis consumer groups retain an unacknowledged message in a pending-entry list when a worker exits.
Reading only new (`>`) entries never recovers it. Transactional outbox publication can also create
duplicate stream entries, and two workers must not normally send the same delivery concurrently.

## Decision

Workers periodically use `XAUTOCLAIM` to take messages idle longer than the configured threshold.
Before network I/O, a worker atomically changes a due delivery from `pending` or `retry_scheduled`
to `processing` and records `processing_started_at`. A fresh processing lease prevents another
worker from sending; a lease older than the Redis claim threshold can be taken over. Workers finish
their current HTTP request before responding to SIGTERM and acknowledge only after durable state is
committed and any retry is scheduled.

## Consequences

- A dead worker no longer strands its pending Redis entry indefinitely.
- Duplicate stream entries are normally acknowledged without duplicate HTTP requests.
- At-least-once delivery still permits a duplicate if a worker dies after the receiver accepts the
  request but before HookRelay commits success. Receivers must deduplicate using the event ID.
- The idle threshold must exceed normal request duration; the default is 30 seconds versus a
  five-second delivery timeout.
