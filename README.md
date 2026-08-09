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

## Current Phase

Phases 0 through 8 are implemented:

- deterministic synthetic and replay market providers;
- normalized trade, candle, and top-five order book ingestion;
- privacy-preserving social replay, parsing, and versioned asset resolution;
- Redpanda-first telemetry with independent TimescaleDB and Parquet consumers;
- an outbox reserved for database-originated domain events;
- event-time 1-minute and 5-minute windows with source watermarks and corrected revisions;
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

The raw replay archive is written to the `raw-data` volume. Qdrant and Neo4j are isolated behind
the `intelligence` profile; the baseline detector and campaign engine continue without them.

## API

- `GET /api/v1/health`
- `GET /api/v1/config`
- `GET /api/v1/source-health`
- `GET /api/v1/market/assets/{asset_id}/latest`
- `GET /api/v1/market/sources/{source}/{asset_id}/health`
- `GET /api/v1/social/platforms/{platform}/latest`
- `GET /api/v1/social/assets/{asset_id}/mentions`
- `GET /api/v1/social/sources/{source}/{platform}/health`
- `GET /api/v1/features/assets/{asset_id}/latest?interval_seconds=60&scope_id={scope}`
- `GET /api/v1/intelligence/assets/{asset_id}/score?scope_id={scope}`
- `GET /api/v1/campaigns?asset_id={asset_id}&scope_id={scope}`
- `GET /api/v1/campaigns/{campaign_id}/evidence`
- `GET /api/v1/alerts?campaign_id={campaign_id}`
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
