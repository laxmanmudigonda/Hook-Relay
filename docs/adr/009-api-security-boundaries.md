# ADR 009: Enforce API and outbound-network security boundaries

- Status: Accepted
- Date: 2026-10-01

## Decision

Authenticated API traffic is limited per tenant with an atomic Redis counter and a 60-second TTL.
The ASGI boundary rejects `/api/v1` request bodies above the configured byte limit before JSON
parsing. Endpoint registration resolves hostnames and rejects loopback, link-local, private,
reserved, and otherwise non-global addresses unless the explicit local-development override is
enabled. Redirect following remains disabled.

New endpoint signing secrets are encrypted before storage using Fernet with a key derived from the
configured application encryption secret. Plaintext is returned only once at creation and is not
logged. Legacy plaintext rows remain readable to support an online transition and should be
rotated in a production migration.

## Consequences

- Redis is part of the authenticated request admission path and rate limits are shared by API
  replicas.
- The local Compose stack explicitly allows private URLs so it can reach `mock-receiver`.
- URL validation reduces SSRF exposure but production deployments must also enforce network egress
  policy and re-resolve destinations safely at connection time to defeat DNS rebinding.
- Changing the encryption key without re-encrypting stored secrets makes encrypted endpoints
  unusable; production keys belong in a managed secret store with a rotation procedure.
