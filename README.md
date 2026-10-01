# HookRelay

HookRelay is a production-oriented learning project for reliable webhook delivery. The finished
system will accept events, persist them, and deliver them to registered HTTP endpoints while making
failures, retries, duplicate delivery, and recovery explicit.

This repository currently contains the **Phase 2 asynchronous delivery pipeline**. It accepts and
persists events, publishes delivery work to Redis Streams, and records worker attempts without
waiting for customer HTTP endpoints in the ingestion request.

## Current architecture

```text
HTTP client
    |
    v
FastAPI (endpoints, events, deliveries)
    |
    +----> PostgreSQL (system of record)
    |
    +----> Redis Stream
              |
              v
        Delivery worker ----> HTTP POST ----> Mock receiver
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

The event response may show `pending`. Inspect a delivery through its returned ID or follow worker
activity:

```bash
curl http://localhost:8000/api/v1/deliveries/DELIVERY_ID
docker compose logs -f worker
```

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

## Phase 2 behavior and decisions

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
- Any 2xx response is successful. Other HTTP responses, connection failures, and timeouts produce a
  failed delivery with a bounded response preview or error message.
- The API commits the event and pending deliveries before publishing their IDs. The worker commits
  attempt state before acknowledging Redis entries.
- Repeating an idempotent request republishes only still-pending deliveries. This provides an
  explicit recovery action when Redis publication failed, while terminal deliveries are not sent
  again.
- Duplicate stream entries are expected. A worker acknowledges entries for terminal deliveries
  without issuing another HTTP request.

The architectural rationale is recorded in
[ADR 001](docs/adr/001-postgresql-as-system-of-record.md) and
[ADR 002](docs/adr/002-redis-streams.md).

### Current delivery semantics

Phase 2 makes exactly one asynchronous attempt. Response bodies are capped in attempt history, and
redirects are not followed. Failed HTTP outcomes are acknowledged after their failure record is
committed; Phase 3 will decide when and how to retry them.

This phase does not yet claim complete at-least-once delivery:

- A crash after the PostgreSQL commit but before Redis publication can strand pending work. An
  idempotent client retry republishes it, while Phase 6 will close the gap with an outbox.
- A worker crash after reading a message can leave it in Redis's pending-entry list. Another worker
  does not reclaim that entry until Phase 7.
- A receiver can process a webhook before a worker crashes, so future recovery may deliver it again.
  Exactly-once webhook delivery is not claimed.

Private-network receiver URLs are intentionally allowed for the local mock receiver. This is not a
production-safe SSRF policy; URL resolution and network egress controls belong to Phase 9.

## Next: Phase 3 (not implemented)

Phase 3 will introduce a tested retry-policy abstraction with exponential backoff, jitter,
retryable failure classification, timeouts, HTTP 5xx and 429 handling, `Retry-After`, and a maximum
attempt count. Dead-letter handling remains Phase 4; signing, authentication, and the transactional
outbox remain later phases.

