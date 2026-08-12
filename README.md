# Scam2Market Backend

Python-first, event-time-aware backend for detecting possible pump-and-dump campaigns from market, social, graph, temporal, and claim-verification signals.

## Product Specification And Planning

The original architecture review supplied for this project is preserved as the first planning
document:

1. [Advanced Implementation Review And Corrected Architecture](docs/planning/Scam2Market_Backend_Advanced_Implementation_Review.md)
2. [Complete Project Blueprint](docs/planning/Scam2Market_Project_Blueprint.md)
3. [Backend Phase Distribution](docs/planning/BACKEND_PHASE_DISTRIBUTION.md)
4. [Initial Backend Implementation Plan](docs/planning/BACKEND_IMPLEMENTATION_PLAN.md)
5. [Phases 2-5 Implementation Notes](docs/implementation/phases-2-5.md)
6. [Phases 6-8 Implementation Notes](docs/implementation/phases-6-8.md)
7. [Phases 9-10 Implementation Report](docs/implementation/PHASE_9_10_IMPLEMENTATION_REPORT.md)
8. [Phases 11-12 Implementation Report](docs/implementation/PHASE_11_12_IMPLEMENTATION_REPORT.md)
9. [CI/CD Pipeline](docs/operations/CI_CD_PIPELINE.md)
10. [Next Services Roadmap](docs/planning/NEXT_SERVICES_ROADMAP.md)
11. [Authentication And Tenant Isolation](docs/implementation/CHECKPOINT_1_AUTH_TENANCY.md)
12. [Live Providers And Durable Checkpoints](docs/implementation/CHECKPOINT_2_LIVE_PROVIDERS.md)
13. [Analyst Dashboard And Notifications](docs/implementation/CHECKPOINT_3_DASHBOARD_NOTIFICATIONS.md)
14. [Calibration, Promotion, And False Positives](docs/implementation/CHECKPOINT_4_MODEL_GOVERNANCE.md)
15. [Production Infrastructure, Recovery, TLS, And SLOs](docs/implementation/CHECKPOINT_5_PRODUCTION_OPERATIONS.md)

## Current Phase

Phases 0 through 12 are implemented for the reproducible local surveillance scope:

- deterministic synthetic and replay market providers;
- live Binance trade, top-five order-book, and closed-candle polling with source cursors;
- live Mastodon public-timeline and RSS social providers with deduplication and optional credentials;
- normalized trade, candle, and top-five order book ingestion;
- privacy-preserving social replay, parsing, and versioned asset resolution;
- Redpanda-first telemetry with independent TimescaleDB and Parquet consumers;
- an outbox reserved for database-originated domain events;
- event-time 1-minute and 5-minute windows with source watermarks and corrected revisions;
- checksum-protected feature-worker state snapshots with database-first offset commits and exact
  arrival-order recovery;
- feature lineage, exact model-input schemas, and low-history confidence;
- baseline market, social, coordination, and temporal detectors;
- separate market, social-coordination, and cross-domain risks with coded missing outputs;
- FastAPI health, latest-state, feature, and score endpoints;
- requirement-level tests for ingestion, replay, windowing, privacy, and fusion behavior.
- persistent campaign state with guarded stage transitions and merge windows;
- idempotent alert creation, cooldown suppression, histories, and transactional outbox events;
- replayable Redis Stream delivery through SSE and WebSocket endpoints;
- deterministic post embeddings and replay-stable narrative clustering;
- optional Qdrant indexing and Neo4j coordination-graph projection;
- graph-derived coordination features with degraded-service isolation;
- official disclosure ingestion and deterministic claim extraction;
- event-time-bounded claim verification that prevents future-document leakage;
- fusion enrichment with explicit optional graph, claim-risk, and legitimate-event evidence.
- append-only evidence snapshots with content hashes, chain-of-custody hashes, and completeness scores;
- alert-linked deterministic explanations and audited evidence manifests;
- investigation assignment, tags, SLAs, timelines, analyst feedback, and feedback adjudication;
- replay evaluation metrics and five cumulative detector ablations;
- MLflow experiment logging, content-addressed model artifacts, and governed model aliases;
- shadow scoring that is database-constrained never to control production alerts.
- integrated Prometheus metrics, optional OTLP traces, Grafana operations dashboards, readiness
  probes, circuit breakers, bounded micro-batching, and visible optional-service degradation;
- Redis token-bucket rate limiting, OIDC/JWT authentication, tenant-aware RBAC, rotatable hashed
  service-account keys, PostgreSQL row-level security, non-root containers, and untrusted
  text/data-poisoning guardrails;
- persistent model-drift reporting and auditable policy proposal governance;
- frozen analyst API for watchlists, assets, timelines, campaigns, alerts, narratives, graphs,
  evidence, investigations, feedback, replay, and evaluation;
- queued replay control worker, generated OpenAPI contract, production-shaped Compose override,
  release verifier, and complete Compose replay CI job.
- tenant-scoped Slack, Teams, email, and signed webhook delivery with idempotent retry history;
- an analyst dashboard for alert triage, campaign state, source readiness, and durable checkpoints.
- deterministic labeled calibration, drift-aware model promotion, and tenant false-positive reports.
- AWS Terraform and Helm production deployment, TLS termination, encrypted backups, restore drills,
  and measurable availability/latency SLOs.

Phase 8 reminder: production official-source connectors and a dedicated analyst-facing
claim/disclosure verification API still need to be completed.

## Additional High-Value Services

Slack, Teams, email, and signed webhooks are now implemented. The next expansion candidates are
portfolio intelligence, cross-platform entity resolution, historical campaign matching, adversarial
simulation, signed evidence exports, SIEM integration, vulnerability scanning, and automated
dependency updates.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Run Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests scripts alembic
.\.venv\Scripts\python.exe -m mypy src tests
.\.venv\Scripts\alembic.exe upgrade head --sql
.\.venv\Scripts\alembic.exe upgrade head
```

## Run With Docker

```powershell
docker compose up --build
```

Migrations and topics are initialized automatically. Run the controlled replay after the core
services are healthy:

```powershell
docker compose --profile demo up replay-scheduler
```

Run the optional graph and verification services with:

```powershell
docker compose --profile intelligence up --build
```

Run the observability stack with Prometheus, Grafana, and the OTLP collector:

```powershell
docker compose --profile observability up --build
```

Validate the production infrastructure and recovery contract with:

```powershell
.\.venv\Scripts\python.exe scripts\validate_operations.py
```

Local service URLs:

- API documentation: `http://localhost:8000/docs`
- analyst dashboard: `http://localhost:8000/dashboard/`
- readiness: `http://localhost:8000/api/v1/ready`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001` (`admin` / development password from Compose)
- Neo4j: `http://localhost:7474`
- Qdrant: `http://localhost:6333`
- MLflow: `http://localhost:5000`

For production-shaped validation, replace every placeholder in `.env.production.example`, load
values from a managed secret store, then apply both Compose files. The repository intentionally does
not contain deployment credentials.

## CI/CD

Every push and pull request runs linting, strict type checks, database migrations, tests, container
builds, and the complete replay regression. The CD workflow publishes a commit-addressed backend
image to `ghcr.io/harish-0412/scam2marke-backend`, adds an SBOM and provenance attestation, and uploads
a digest-pinned deployment bundle.

Automatic staging deployment is intentionally opt-in. See the
[CI/CD Pipeline](docs/operations/CI_CD_PIPELINE.md) for free-tier boundaries and the protected
self-hosted runner setup.

The raw replay archive is written to the `raw-data` volume. Qdrant and Neo4j are isolated behind
the `intelligence` profile; the baseline detector and campaign engine continue without them.

## API

- `GET /api/v1/auth/me`
- `POST /api/v1/auth/tenants`
- `POST /api/v1/auth/memberships`
- `GET|POST /api/v1/auth/service-accounts`
- `POST /api/v1/auth/service-accounts/{account_id}/keys/{key_id}/rotate`
- `DELETE /api/v1/auth/service-accounts/{account_id}/keys/{key_id}`
- `GET /api/v1/health`
- `GET /api/v1/config`
- `GET /api/v1/source-health`
- `GET /api/v1/ready`
- `GET /api/v1/metrics`
- `GET|POST /api/v1/watchlists`
- `POST|DELETE /api/v1/watchlists/{watchlist_id}/assets`
- `GET /api/v1/assets/{asset_id}/overview`
- `GET /api/v1/assets/{asset_id}/scores`
- `GET /api/v1/assets/{asset_id}/timeline`
- `GET /api/v1/market/assets/{asset_id}/latest`
- `GET /api/v1/market/sources/{source}/{asset_id}/health`
- `GET /api/v1/social/platforms/{platform}/latest`
- `GET /api/v1/social/assets/{asset_id}/mentions`
- `GET /api/v1/social/sources/{source}/{platform}/health`
- `GET /api/v1/features/assets/{asset_id}/latest?interval_seconds=60&scope_id={scope}`
- `GET /api/v1/intelligence/assets/{asset_id}/score?scope_id={scope}`
- `GET /api/v1/campaigns?asset_id={asset_id}&scope_id={scope}`
- `GET /api/v1/campaigns/{campaign_id}/evidence`
- `GET /api/v1/campaigns/{campaign_id}`
- `GET /api/v1/campaigns/{campaign_id}/graph`
- `GET /api/v1/alerts?campaign_id={campaign_id}`
- `GET /api/v1/alerts/{alert_id}`
- `POST /api/v1/alerts/{alert_id}/acknowledge`
- `GET /api/v1/alerts/{alert_id}/evidence`
- `GET /api/v1/alerts/{alert_id}/explanation`
- `GET /api/v1/evidence/{snapshot_id}/manifest` (audited access headers required)
- `POST /api/v1/investigations`
- `GET /api/v1/investigations?scope_id={scope}`
- `PATCH /api/v1/investigations/{investigation_id}`
- `POST /api/v1/investigations/{investigation_id}/events`
- `POST /api/v1/investigations/{investigation_id}/feedback`
- `POST /api/v1/feedback/{feedback_id}/adjudicate`
- `POST /api/v1/replays`
- `GET /api/v1/replays`
- `POST /api/v1/replays/{replay_session_id}/start`
- `POST /api/v1/replays/{replay_session_id}/pause`
- `POST /api/v1/replays/{replay_session_id}/evaluate`
- `POST /api/v1/models/artifacts`
- `PUT /api/v1/models/{model_family}/aliases/{alias}`
- `POST /api/v1/shadow-scores`
- `GET /api/v1/assets/{asset_id}/narratives`
- `GET /api/v1/narratives/{narrative_id}`
- `GET|POST /api/v1/operations/model-drift`
- `GET /api/v1/operations/worker-checkpoints`
- `GET|POST /api/v1/operations/policy-proposals`
- `GET /api/v1/stream/alerts` (server-sent events)
- `WS /api/v1/ws/alerts?after_id={redis_stream_id}`

## Architecture Docs

- [Domain Model](docs/architecture/domain-model.md)
- [Service Map](docs/architecture/service-map.md)
- [Demo Scenario](docs/architecture/demo-scenario.md)
- [Scope Reset](docs/architecture/scope-reset.md)
- [Architecture Decision Records](docs/architecture/decisions)
- [Phases 2-5 Implementation](docs/implementation/phases-2-5.md)
- [Phases 6-8 Implementation](docs/implementation/phases-6-8.md)
- [Phases 9-10 Implementation Report](docs/implementation/PHASE_9_10_IMPLEMENTATION_REPORT.md)
- [Phases 11-12 Implementation Report](docs/implementation/PHASE_11_12_IMPLEMENTATION_REPORT.md)
- [Production Readiness](docs/operations/PRODUCTION_READINESS.md)
- [Backup And Restore Runbook](docs/operations/BACKUP_RESTORE_RUNBOOK.md)
- [CI/CD Pipeline](docs/operations/CI_CD_PIPELINE.md)
- [Next Services Roadmap](docs/planning/NEXT_SERVICES_ROADMAP.md)
