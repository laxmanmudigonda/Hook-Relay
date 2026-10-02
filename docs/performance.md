# Local performance baseline

Measured on 2026-10-02 against the Docker Desktop Compose stack using
`scripts/load_test.py --requests 50 --concurrency 10`:

- 50/50 responses were HTTP 201.
- Elapsed time: 1.562 seconds (32.01 requests/second).
- API latency: p50 200.89 ms; p95 689.26 ms.

This is a small local baseline, not a production capacity claim. It includes authentication,
rate-limit lookup, PostgreSQL event/delivery/outbox commits, and local container overhead. The run
also correctly consumed 50 entries from the configured 120-request tenant budget; tests that poll
the API immediately afterward must use a separate tenant/key or clear the local rate-limit key.
