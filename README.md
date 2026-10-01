# HookRelay

HookRelay is a production-oriented learning project for reliable webhook delivery. The finished
system will accept events, persist them, and deliver them to registered HTTP endpoints while making
failures, retries, duplicate delivery, and recovery explicit.

This repository currently contains **Phase 4 dead-letter handling and manual replay**. It accepts
and persists events, retries transient receiver failures, exposes exhausted deliveries for
inspection, and can replay them without deleting their attempt history.

## Current architecture

```text
HTTP client
    |
    v
FastAPI (endpoints, events, deliveries)
    |
    +----> PostgreSQL (system of record)
    |
    +----> Redis Stream <---- due retries from Redis sorted set
              |
              v
        Delivery worker ----> HTTP POST ----> Mock receiver
              |
              +---- transient failure ----> delayed retry sorted set
```

- `/health` is a liveness check. It proves the API process can serve requests and deliberately does
  not depend on PostgreSQL.
- `/ready` verifies both PostgreSQL and Redis and returns HTTP 503 when either required dependency
  is unavailable.
- SQLAlchemy uses its async API with `asyncpg` so request handlers do not block the event
  loop during database I/O.
- Alembic owns schema changes. Application startup applies migrations but never calls
  `create_all()`.

## Requirements

The supported path requires only Docker Desktop with Docker Compose. For host development, use
Python 3.12 or newer.

## Run locally

Copy the example environment file only if you want to customize local settings:

```bash
cp .env.example .env
```

Build and start PostgreSQL, Redis, the API, worker, and mock receiver:

```bash
docker compose up -d --build
```

Then check:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
docker compose ps
```

Interactive API documentation is available at <http://localhost:8000/docs>.
The mock receiver is available at <http://localhost:8001/docs>.

Register a successful receiver and submit an event:

```bash
curl -X POST http://localhost:8000/api/v1/endpoints \
  -H "Content-Type: application/json" \
  -d '{"url":"http://mock-receiver:8001/webhooks/success","description":"Local demo"}'

curl -X POST http://localhost:8000/api/v1/events \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-payment-1" \
  -d '{"event_type":"payment.completed","payload":{"payment_id":"pay_123","amount":2499}}'
```

The event response may show `pending` or `retry_scheduled`. Inspect a delivery through its returned
ID or follow worker activity:

```bash
curl http://localhost:8000/api/v1/deliveries/DELIVERY_ID
docker compose logs -f worker
```

After a retryable failure exhausts its attempt budget, replay it once the receiver is healthy:

```bash
curl -X POST http://localhost:8000/api/v1/deliveries/DELIVERY_ID/replay
```

Replay returns HTTP 202, resets the current retry-cycle count, and queues the same delivery ID.
The endpoint must still be enabled.

Stop the services with `docker compose down`. Add `--volumes` only when you intentionally want to
delete the local PostgreSQL and Redis data volumes.

## Development checks

Run checks in disposable containers so the host does not need Python:

```bash
docker build --target test -t hookrelay-test .
```

Or, with Python 3.12+ installed on the host:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

Run migration checks against the Compose database:

```bash
docker compose exec api alembic current
docker compose exec api alembic check
```

Run the end-to-end integration test against the active Compose network:

```bash
docker run --rm --network hookrelay_default \
  -e HOOKRELAY_INTEGRATION_BASE_URL=http://api:8000 \
  -e HOOKRELAY_INTEGRATION_RECEIVER_URL=http://mock-receiver:8001 \
  hookrelay-test pytest tests/integration
```

Inspect the consumer group and pending-entry list:

```bash
docker compose exec redis redis-cli XINFO GROUPS hookrelay:deliveries
docker compose exec redis redis-cli XPENDING hookrelay:deliveries hookrelay-workers
```

## Configuration

All application settings use the `HOOKRELAY_` prefix. See `.env.example`. The checked-in values are
local-development defaults only; real credentials and `.env` files must not be committed.

## Phase 4 behavior and decisions

- PostgreSQL 17 is pinned by major version for reproducibility while retaining patch updates.
- Liveness and readiness are separate because a failed dependency should remove an instance from
  traffic without falsely claiming that its process is dead.
- A seeded development tenant is used until API-key authentication arrives in Phase 8. Every API
  query is still tenant-scoped so that boundary is explicit in the code.
- An event currently fans out to every enabled endpoint. Event subscriptions are not needed for the
  current MVP and have not been invented prematurely.
- `Idempotency-Key` is unique per tenant. Repeating a key returns the original event and does not
  deliver it again. Reusing a key with a different event type or payload returns HTTP 409.
- Each event/endpoint pair is unique, and attempt numbers are unique within a delivery.
- Tenant deletion cascades through owned data, event deletion cascades through delivery history,
  and endpoint deletion is restricted once delivery history refers to it. No deletion routes are
  exposed in Phase 1.
- Any 2xx response is successful. Timeouts, network failures, HTTP 408, 425, 429, and 5xx responses
  are retryable. Other 4xx responses fail immediately because repeating an invalid request usually
  cannot make it valid.
- Retry delays use capped exponential backoff with full jitter. A valid `Retry-After` header on a
  retryable response acts as a minimum delay, bounded by the configured maximum so a receiver
  cannot postpone work indefinitely.
- PostgreSQL is authoritative for status, attempt count, history, and `next_attempt_at`. A Redis
  sorted set is the efficient due-time schedule. A Lua script atomically removes due IDs from that
  set and appends them to the delivery stream.
- The API commits the event and pending deliveries before publishing their IDs. The worker commits
  attempt state before acknowledging Redis entries.
- Repeating an idempotent request republishes incomplete pending or retry-scheduled deliveries.
  This provides an explicit recovery action when Redis publication or retry scheduling failed,
  while terminal deliveries are not sent again.
- Duplicate stream entries are expected. A worker acknowledges entries for terminal deliveries
  without issuing another HTTP request.
- A retryable failure that exhausts its configured attempts becomes `dead_lettered`. A
  non-retryable response such as HTTP 400 becomes `failed` immediately and is not treated as retry
  exhaustion.
- Manual replay reuses the existing delivery. `attempt_count` remains the lifetime count and
  attempt numbers remain monotonic; `current_attempt_count` is reset for a fresh retry budget.
  `replay_count` and `last_replayed_at` make the action visible.
- Replay is restricted to dead-lettered deliveries. Replaying a pending, failed, or delivered
  delivery returns HTTP 409, as does replay to a disabled endpoint.

The architectural rationale is recorded in
[ADR 001](docs/adr/001-postgresql-as-system-of-record.md) and
[ADR 002](docs/adr/002-redis-streams.md), and
[ADR 003](docs/adr/003-retry-policy-and-scheduling.md), and
[ADR 004](docs/adr/004-dead-letters-and-replay.md).

### Retry configuration

The defaults are five total attempts, a one-second base delay, a 60-second delay cap, and a
500-millisecond scheduler interval. Configure them with
`HOOKRELAY_MAX_DELIVERY_ATTEMPTS`, `HOOKRELAY_RETRY_BASE_DELAY_SECONDS`,
`HOOKRELAY_RETRY_MAX_DELAY_SECONDS`, and `HOOKRELAY_RETRY_SCHEDULER_INTERVAL_MS`.
Response bodies remain bounded in attempt history, and redirects are not followed.

To demonstrate two failures followed by success, register this endpoint before submitting an
event (use a unique `key` for each demonstration):

```text
http://mock-receiver:8001/webhooks/flaky?key=phase3-demo&failures=2
```

The resulting delivery finishes as `delivered` with three attempt records. An always-failing
endpoint finishes as `dead_lettered` after the configured maximum.

### Dead-letter and replay demonstration

Register a flaky endpoint with `failures=5` while the default maximum is five, then submit an
event. The delivery becomes `dead_lettered` with attempts 1 through 5. Calling its replay endpoint
starts a fresh retry cycle; because the mock receiver now recovers, lifetime attempt 6 succeeds.
All six attempt records remain available through the delivery and attempts APIs.

### Current delivery semantics and limitations

This phase does not yet claim complete at-least-once delivery:

- A crash after the PostgreSQL commit but before Redis publication can strand pending work. An
  idempotent client retry republishes it, while Phase 6 will close the gap with an outbox.
- A worker crash after reading a message can leave it in Redis's pending-entry list. Another worker
  does not reclaim that entry until Phase 7.
- PostgreSQL status and the Redis retry schedule cannot yet be changed atomically. If scheduling
  fails after the database commit, the original stream entry remains unacknowledged and repeating
  the idempotent event request can republish it. The transactional outbox in Phase 6 and pending
  message recovery in Phase 7 close the automatic-recovery gaps.
- The replay state commit and Redis publication are also not atomic yet. If replay publication
  fails, the delivery remains `pending`; repeating the original idempotent event request can
  republish it. Phase 6 will move this publication through the transactional outbox.
- A receiver can process a webhook before a worker crashes, so future recovery may deliver it again.
  Exactly-once webhook delivery is not claimed.

Private-network receiver URLs are intentionally allowed for the local mock receiver. This is not a
production-safe SSRF policy; URL resolution and network egress controls belong to Phase 9.

## Next: Phase 5 (not implemented)

Phase 5 will add HMAC webhook signatures, timestamp tolerance, receiver-side verification, and
tests proving modified payloads or incorrect secrets do not verify. Authentication and the
transactional outbox remain later phases.

