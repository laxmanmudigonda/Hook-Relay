# ADR 010: Prefer structured logs and metrics before distributed tracing

- Status: Accepted
- Date: 2026-10-02

HookRelay emits JSON logs with correlation and domain identifiers, and Prometheus metrics with
bounded labels for HTTP requests, deliveries, outbox publication, and abandoned-message recovery.
Raw tenant IDs, endpoint URLs, secrets, payloads, and exception request bodies are not metric labels.

Tracing is deferred until a collector and an operational use case exist. Durable event and delivery
IDs bridge the asynchronous boundary today; adding spans without storage, sampling, and ownership
would create instrumentation cost without usable diagnosis.
