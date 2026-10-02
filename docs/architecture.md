# Architecture

```text
Client --API key--> FastAPI --transaction--> PostgreSQL
                         |                    | outbox
                         |                    v
                         |                 Publisher --> Redis Stream
                         |                                  |
                         +<-- status API                Worker(s)
                                                            |
                                                            v
                                                     Signed HTTP webhook
```

PostgreSQL is authoritative. The outbox closes the database/queue publication gap. Redis Streams
provide consumer groups and pending-entry recovery; the retry sorted set provides due-time ordering.
At-least-once delivery is explicit: receivers deduplicate using the stable event ID.

See the numbered ADRs for the alternatives and tradeoffs made at each phase.
