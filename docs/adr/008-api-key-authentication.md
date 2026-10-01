# ADR 008: Authenticate requests with tenant-scoped API keys

- Status: Accepted
- Date: 2026-10-01

## Decision

All `/api/v1` routes require an `X-API-Key`. Only a SHA-256 digest, a non-secret prefix, and key
metadata are stored. Authentication resolves the owning tenant and every resource query uses that
tenant ID; cross-tenant identifiers therefore return the same 404 as missing resources. Health and
readiness probes remain unauthenticated.

The initial migration creates one local-development key for the seeded tenant. Production keys
must be generated with high entropy, supplied once to their owner, and rotated by inserting a new
digest before revoking the old row.

## Consequences

- Tenant identity is no longer selected from a global application setting.
- Raw API keys cannot be recovered from the database.
- API-key compromise grants tenant-level access until revocation; TLS and secret-manager storage
  are mandatory outside local development.
