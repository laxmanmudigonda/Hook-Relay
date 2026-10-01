# ADR 005: Versioned HMAC webhook signatures

## Context

TLS protects webhook traffic in transit but does not let a receiver prove the request originated
from HookRelay or that an intermediary did not change its body. A captured valid request could also
be replayed later unless the receiver checks freshness.

## Decision

Generate an independent 256-bit-or-greater random secret for every endpoint. Return it only from
the endpoint creation response and omit it from endpoint list and detail responses.

Sign the exact outbound body bytes with HMAC-SHA256. The signed input is the decimal Unix timestamp,
a literal period, and the raw body. Send the result as `X-HookRelay-Signature: v1=<hex>`, alongside
`X-HookRelay-Timestamp` and the stable `X-HookRelay-Event-ID`. The `v1` prefix permits a future
format or algorithm migration.

Provide a verification helper that rejects missing or malformed headers, uses constant-time
comparison, and enforces a configurable timestamp tolerance that rejects both stale and excessively
future-dated requests. Receivers must verify raw bytes before decoding JSON.

## Alternatives

- A static installation-wide secret has less operational state but one disclosure compromises all
  endpoints and makes isolated rotation impossible.
- Signing canonicalized JSON is fragile across languages and serializers; signing transmitted
  bytes has an unambiguous contract.
- Asymmetric signatures avoid sharing verification secrets but introduce key distribution and
  rotation complexity that is not justified at this phase.
- Signing only the body detects modification but offers no freshness signal against replay.

## Consequences

Receivers can authenticate HookRelay requests, detect modified bodies, and reduce replay risk with
timestamp checks. Retries carry fresh timestamps and signatures while retaining the stable event
identifier needed for receiver idempotency.

Secrets are currently stored plaintext in PostgreSQL because workers need them for signing. This is
an explicit local portfolio simplification, not a production secret-storage claim. A production
design would add KMS-backed encryption, access controls, rotation, and auditability. The mock
receiver's secret-registration route is test-only and models an out-of-band exchange; it is not a
production management API.
