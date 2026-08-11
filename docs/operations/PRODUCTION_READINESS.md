# Production Readiness

## Required Before Deployment

- Set unique PostgreSQL, Neo4j, Grafana, API, and pseudonymization secrets through a managed secret
  store. Development values are forbidden.
- Set `REQUIRE_API_KEY=true`, `RATE_LIMIT_FAIL_CLOSED=true`, strict `ALLOWED_ORIGINS`, and an OTLP
  endpoint. Rotate service credentials with overlapping key versions and audit every rotation.
- Place TLS and an authenticated gateway in front of the API. Do not publish database, Redis,
  Redpanda, Neo4j, Qdrant, or MLflow ports.
- Configure encrypted backups, retention policies, alert routing, and on-call ownership.
- Verify `/api/v1/health`, `/api/v1/ready`, Prometheus scraping, Grafana panels, and trace receipt.
- Run migrations, the complete test suite, the Compose replay regression, and restore rehearsal.

## Degradation Policy

PostgreSQL and Redis are readiness-critical. Neo4j, Qdrant, MLflow, and OTX are optional enrichment
dependencies: failures are reported, circuit-broken, and must not stop baseline scoring. Shadow models
never control alerts. Untrusted text is treated as data, scanned before LLM use, and never inserted into
system prompts.
