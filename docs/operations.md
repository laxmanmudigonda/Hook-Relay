# Operations guide

HookRelay exposes API metrics at `api:8000/metrics`, worker metrics at `worker:9000/metrics`, and
publisher metrics at `publisher:9001/metrics` so an in-cluster scraper can collect each process.
Only the API endpoint is host-published locally; restrict it at the ingress in public deployments. Every API
response includes `X-Request-ID`; callers may provide one, and JSON API logs carry the same value.
Worker logs include delivery, event, endpoint, and Redis message identifiers where available.

## Suggested alerts

- Readiness unavailable for 2 minutes: dependency or migration incident.
- `rate(hookrelay_outbox_publications_total{result="failed"}[5m]) > 0` for 5 minutes: Redis or
  publisher failure.
- Unpublished outbox row age above 2 minutes: publication backlog.
- Redis consumer-group pending count or oldest pending age increasing for 5 minutes: stuck workers.
- Dead-letter rate above the service-specific baseline: receiver outage or contract regression.
- p95 `hookrelay_delivery_duration_seconds` near the configured timeout: receiver degradation.
- Sustained HTTP 5xx ratio above 1% and 429 ratio above the expected client budget.

Distributed tracing is deliberately deferred. The current topology has one API transaction and an
asynchronous delivery boundary with durable IDs, but no trace collector. Request/event/delivery IDs
already support investigation without adding an unoperated telemetry dependency. OpenTelemetry is
appropriate when HookRelay is deployed alongside a collector and trace retention/query tooling.
