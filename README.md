# HookRelay

HookRelay is a production-oriented learning project for reliable webhook delivery. The finished
system will accept events, persist them, and deliver them to registered HTTP endpoints while making
failures, retries, duplicate delivery, and recovery explicit.

This repository currently contains **Phase 6 transactional publication**. It accepts and persists
events, retries transient failures, supports dead-letter replay, signs every outbound request, and
uses a PostgreSQL outbox so committed delivery work is not lost during a Redis outage.

## Current architecture

```text
HTTP client
    |
    v
FastAPI (endpoints, events, deliveries)
    |
    +----> PostgreSQL (events + deliveries + outbox, one transaction)
                    |
                    v
             Outbox publisher ----> Redis Stream <---- due retries
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

The endpoint creation response contains a generated `signing_secret`. Store it securely: HookRelay
returns it only from `POST /api/v1/endpoints`; endpoint list and detail responses never expose it.

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

## Phase 6 behavior and decisions

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
- The API commits an event, its deliveries, and corresponding outbox rows atomically. It never
  publishes directly to Redis, so Redis downtime cannot create a commit/publish gap.
- A dedicated publisher locks unpublished outbox rows with `FOR UPDATE SKIP LOCKED`, appends each
  delivery ID to Redis, and marks the row published. Multiple publishers can safely share work.
- Repeating an idempotent request creates fresh outbox rows only for incomplete pending or
  retry-scheduled deliveries; terminal deliveries are not sent again.
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
- Every delivery attempt includes `X-HookRelay-Signature`, `X-HookRelay-Timestamp`, and
  `X-HookRelay-Event-ID`. The signature is HMAC-SHA256 over the timestamp, a period, and the exact
  request body bytes.
- Each endpoint receives an independent, cryptographically random signing secret. It is returned
  once during endpoint creation and omitted from later API responses.
- Retries sign the same event envelope again with a fresh timestamp. Receivers should use the
  stable event ID for idempotency and reject timestamps outside their allowed clock-skew window.

The architectural rationale is recorded in
[ADR 001](docs/adr/001-postgresql-as-system-of-record.md) and
[ADR 002](docs/adr/002-redis-streams.md), and
[ADR 003](docs/adr/003-retry-policy-and-scheduling.md), and
[ADR 004](docs/adr/004-dead-letters-and-replay.md), and
[ADR 005](docs/adr/005-webhook-signing.md), and
[ADR 006](docs/adr/006-transactional-outbox.md).

### Webhook signature contract

For raw request body bytes `body` and the decimal Unix timestamp header `timestamp`, HookRelay
computes:

```text
signed_payload = UTF8(timestamp) + "." + body
signature = "v1=" + HEX(HMAC-SHA256(endpoint_secret, signed_payload))
```

Receivers must verify against the raw body before parsing JSON. Re-serializing JSON can change its
bytes and invalidate a legitimate signature. The included Python verification helper uses
constant-time comparison and a default five-minute timestamp tolerance:

```python
from hookrelay.delivery.signing import verify_webhook_signature

valid = verify_webhook_signature(
    endpoint_secret,
    request.headers,
    await request.body(),
    tolerance_seconds=300,
)
```

The mock receiver's `/webhooks/signed` route demonstrates verification. Its
`/test/signing-secrets/{key}` setup route exists only for deterministic local integration tests and
must not be treated as a production secret-distribution design.

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

- A worker crash after reading a message can leave it in Redis's pending-entry list. Another worker
  does not reclaim that entry until Phase 7.
- Retry scheduling still uses Redis directly. If scheduling fails after the database commit, the
  original stream entry remains unacknowledged for Phase 7 recovery.
- The publisher is intentionally at-least-once: a crash after `XADD` but before marking the outbox
  row published can create a duplicate stream entry. Workers therefore must remain idempotent.
- A receiver can process a webhook before a worker crashes, so future recovery may deliver it again.
  Exactly-once webhook delivery is not claimed.

Private-network receiver URLs are intentionally allowed for the local mock receiver. This is not a
production-safe SSRF policy; URL resolution and network egress controls belong to Phase 9.

Signing secrets are currently stored in plaintext in the local PostgreSQL database because the
worker must retrieve them to compute HMACs. Production deployment would encrypt them with a
KMS-backed key, tightly restrict database access, support rotation, and ensure they never appear in
logs. Phase 5 does not claim production-grade secret management.

## Next: Phase 7 (not implemented)

Phase 7 will reclaim abandoned Redis pending entries, protect concurrent duplicate processing,
and verify graceful worker shutdown and crash recovery. Authentication remains a later phase.

