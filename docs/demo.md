# Five-minute demo

1. Run `docker compose up -d --build` and check `/ready`.
2. Register the mock success endpoint with the development API key.
3. Submit an idempotent event and show its delivery becoming `delivered`.
4. Submit to the flaky receiver and show attempt history plus jittered retries.
5. Stop Redis, submit an event, show the unpublished outbox row, restart Redis, and show recovery.
6. Open `/metrics`, show JSON logs, then explain API-key tenant isolation and encrypted secrets.

The README contains copyable commands and the exact signature contract.
