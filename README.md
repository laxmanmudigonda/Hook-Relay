# HookRelay

Reliable, multi-tenant webhook delivery with durable queues, automatic retries, signed requests,
dead-letter recovery, and operational visibility.

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-Streams-DC382D?logo=redis&logoColor=white)](https://redis.io/)

HookRelay accepts application events, commits them durably, and delivers signed HTTP webhooks to
registered endpoints. It makes the difficult parts of webhook infrastructure explicit: partial
failures, retries, duplicate delivery, worker crashes, queue recovery, tenant isolation, and
observability.

## Why HookRelay?

- **No commit/publish gap:** events, deliveries, and outbox records commit in one PostgreSQL
  transaction before a publisher transfers work to Redis.
- **At-least-once delivery:** Redis consumer groups, database processing leases, and `XAUTOCLAIM`
  recover work abandoned by crashed workers.
- **Controlled retries:** transient failures use capped exponential backoff with full jitter and
  bounded `Retry-After` support.
- **Inspectable failures:** exhausted deliveries enter a dead-letter state with complete attempt
  history and can be replayed manually.
- **Authenticated delivery:** every webhook is HMAC-SHA256 signed with an endpoint-specific secret.
- **Tenant isolation:** hashed API keys resolve tenant identity and every resource query is scoped.
- **Security boundaries:** body-size limits, rate limiting, SSRF-aware URL checks, disabled
  redirects, and encrypted signing secrets.
- **Operations built in:** JSON logs, request IDs, Prometheus metrics, health/readiness checks, and
  a developer dashboard.

## Architecture

```text
Client -- X-API-Key --> FastAPI
                            |
             one transaction: event + deliveries + outbox
                            |
                            v
                       PostgreSQL
                            |
                            v
                    Outbox publisher
                            |
                            v
Retry schedule <---- Redis Streams consumer group
      ^                     |
      |                     v
      +-------------- Delivery worker
                            |
                     signed HTTP POST
                            v
                    Webhook receiver
```

PostgreSQL owns delivery state and history. Redis is the work-distribution and retry-timing layer.
Duplicate delivery remains possible by design, so receivers should deduplicate using the stable
`X-HookRelay-Event-ID`. See the [architecture overview](docs/architecture.md) and
[decision records](docs/adr/) for details.

## Quick start

Prerequisites: Docker Desktop and Docker Compose.

```bash
docker compose up -d --build
```

Verify the stack:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
docker compose ps
```

Local services:

- API documentation: <http://localhost:8000/docs>
- Developer dashboard: <http://localhost:8000/dashboard>
- Prometheus metrics: <http://localhost:8000/metrics>
- Mock receiver: <http://localhost:8001/docs>
- Development API key: `hr_dev_local_change_me`

The checked-in credentials and private-network override are for local development only.

## Send your first webhook

Register the included successful receiver:

```bash
curl -X POST http://localhost:8000/api/v1/endpoints \
  -H "X-API-Key: hr_dev_local_change_me" \
  -H "Content-Type: application/json" \
  -d '{"url":"http://mock-receiver:8001/webhooks/success","description":"Local demo"}'
```

The response contains a `signing_secret`. It is returned only once and encrypted at rest.

Submit an event:

```bash
curl -X POST http://localhost:8000/api/v1/events \
  -H "X-API-Key: hr_dev_local_change_me" \
  -H "Idempotency-Key: demo-payment-1" \
  -H "Content-Type: application/json" \
  -d '{"event_type":"payment.completed","payload":{"payment_id":"pay_123","amount":2499}}'
```

Inspect a returned delivery ID:

```bash
curl -H "X-API-Key: hr_dev_local_change_me" \
  http://localhost:8000/api/v1/deliveries/DELIVERY_ID
```

Or follow worker activity:

```bash
docker compose logs -f worker
```

For retries, dead-letter replay, Redis-outage recovery, and metrics, follow the
[five-minute demo](docs/demo.md).

## Delivery behavior

| Receiver result | HookRelay action |
| --- | --- |
| Any `2xx` | Mark delivered |
| Timeout or network error | Retry |
| `408`, `425`, `429`, or `5xx` | Retry |
| Other `4xx` | Fail immediately |
| Retry budget exhausted | Dead-letter |

Defaults are five attempts, a one-second base delay, a 60-second delay cap, and full jitter.
Retries preserve the event ID but receive a fresh signature timestamp.

Replay a recovered dead-lettered delivery:

```bash
curl -X POST http://localhost:8000/api/v1/deliveries/DELIVERY_ID/replay \
  -H "X-API-Key: hr_dev_local_change_me"
```

Replay retains lifetime attempt history while starting a fresh retry budget.

## Webhook signatures

Every outbound request includes:

- `X-HookRelay-Signature`
- `X-HookRelay-Timestamp`
- `X-HookRelay-Event-ID`

The signature covers the exact request bytes:

```text
signed_payload = UTF8(timestamp) + "." + body
signature = "v1=" + HEX(HMAC-SHA256(endpoint_secret, signed_payload))
```

Receivers should verify before parsing JSON, use constant-time comparison, enforce a timestamp
tolerance, and deduplicate by event ID. A Python helper is included:

```python
from hookrelay.delivery.signing import verify_webhook_signature

valid = verify_webhook_signature(
    endpoint_secret,
    request.headers,
    await request.body(),
    tolerance_seconds=300,
)
```

## Testing

Run lint, formatting, and unit tests in a disposable image:

```bash
docker build --target test -t hookrelay-test .
```

Run the end-to-end test against the active Compose stack:

```bash
docker run --rm --network hookrelay_default \
  -e HOOKRELAY_INTEGRATION_BASE_URL=http://api:8000 \
  -e HOOKRELAY_INTEGRATION_RECEIVER_URL=http://mock-receiver:8001 \
  -e HOOKRELAY_INTEGRATION_API_KEY=hr_dev_local_change_me \
  hookrelay-test pytest tests/integration -q
```

Check migration/model consistency:

```bash
docker compose exec api alembic current
docker compose exec api alembic check
```

## Observability

| Process | Metrics endpoint |
| --- | --- |
| API | `api:8000/metrics` / <http://localhost:8000/metrics> |
| Worker | `worker:9000/metrics` inside Compose |
| Publisher | `publisher:9001/metrics` inside Compose |

API responses include `X-Request-ID`; structured logs carry the same value. Worker logs include
delivery, event, endpoint, and Redis message identifiers where applicable. See the
[operations guide](docs/operations.md) for alerting recommendations.

## Performance baseline

Run the reproducible load probe:

```bash
python scripts/load_test.py --requests 100 --concurrency 10
```

The documented local Docker run achieved 50/50 successful submissions at 32.01 requests/second,
with 200.89 ms p50 and 689.26 ms p95 latency. These are local measurements, not a production
capacity claim. See [performance.md](docs/performance.md) for context.

## Configuration

All settings use the `HOOKRELAY_` prefix. Copy `.env.example` to `.env` to override Compose
defaults. Configuration covers database and Redis connections, retries and timeouts, processing
leases, outbox batches, request limits, encryption, and metrics ports.

Never deploy the local API key, database password, encryption key, or private-network URL override
to production.

## Documentation

- [Architecture](docs/architecture.md)
- [Operations](docs/operations.md)
- [Performance](docs/performance.md)
- [Five-minute demo](docs/demo.md)
- [Architecture decision records](docs/adr/)

## Production considerations

HookRelay is a complete Docker-based portfolio/MVP. An internet-facing deployment should also
provide TLS and ingress policy, managed secrets and rotation, connection-time egress enforcement,
database backups and recovery testing, a deployed metrics backend, alert routing, and CI/CD.

## Stop the stack

```bash
docker compose down
```

Add `--volumes` only when you intentionally want to delete local PostgreSQL and Redis data.
