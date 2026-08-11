# Checkpoint 1: Authentication, RBAC, And Tenant Isolation

## Implemented Boundary

- OIDC access-token validation through issuer, audience, JWKS, expiry, issued-at, and subject
  checks. Only RS256 and ES256 identity-provider signatures are accepted.
- Explicit `PLATFORM_ADMIN`, `TENANT_ADMIN`, `ANALYST`, `REVIEWER`, `VIEWER`, and `SERVICE` roles
  with permission-based API authorization.
- A development identity mode for local replay and tests. Production configuration disables this
  mode and fails closed when a bearer token is absent or invalid.
- Tenant, membership, service-account, service-key, and authentication-event persistence.
- One-time service-account secrets in the `s2m_<key-id>.<secret>` format. Only a peppered HMAC-SHA256
  digest is stored.
- Atomic key rotation with immediate old-key revocation, expiration enforcement, last-used tracking,
  tenant-scoped key management, and successful key-authentication auditing.
- Tenant ownership on campaigns, alerts, investigations, watchlists, replays, audits, model-drift
  events, and policy proposals.
- Request-scoped PostgreSQL tenant context plus forced row-level-security policies. API queries that
  expose tenant-owned collections also carry explicit tenant predicates for defense in depth.

## Production Configuration

Set these values through the deployment secret store:

```dotenv
AUTH_REQUIRED=true
DEVELOPMENT_AUTH_ENABLED=false
OIDC_ISSUER=https://identity.example/
OIDC_AUDIENCE=scam2market-api
OIDC_JWKS_URL=https://identity.example/.well-known/jwks.json
OIDC_TENANT_CLAIM=tenant_id
OIDC_ROLES_CLAIM=roles
SERVICE_KEY_PEPPER=<high-entropy-managed-secret>
```

The database runtime role should not be a PostgreSQL superuser. Superusers bypass row-level
security by design; the production infrastructure checkpoint provisions separate migration and
runtime identities.

## Verification

The checkpoint test suite verifies key parsing and peppering, viewer mutation denial, production
fail-closed authentication, tenant-separated watchlist reads, successful service-key authentication,
atomic rotation, and rejection of the old key after rotation. CI also reverses and reapplies this
migration to verify downgrade safety.
