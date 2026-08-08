# Scam2Market Backend

Python-first, event-time-aware backend for detecting possible pump-and-dump campaigns from market, social, graph, temporal, and claim-verification signals.

## Product Specification And Planning

The original architecture review supplied for this project is preserved as the first planning
document:

1. [Advanced Implementation Review And Corrected Architecture](docs/planning/Scam2Market_Backend_Advanced_Implementation_Review.md)
2. [Backend Phase Distribution](docs/planning/BACKEND_PHASE_DISTRIBUTION.md)
3. [Initial Backend Implementation Plan](docs/planning/BACKEND_IMPLEMENTATION_PLAN.md)
4. [Phases 2-5 Implementation Notes](docs/implementation/phases-2-5.md)

## Current Phase

Phases 0 through 5 are implemented:

- deterministic synthetic and replay market providers;
- normalized trade, candle, and top-five order book ingestion;
- privacy-preserving social replay, parsing, and versioned asset resolution;
- TimescaleDB persistence, Redis online state, immutable Parquet archives, and an outbox;
- event-time 1-minute and 5-minute feature windows with watermarks and revisions;
- feature lineage, exact model-input schemas, and low-history confidence;
- baseline market, social, coordination, and temporal detectors;
- market regime, liquidity classification, conservative fusion, and missing-output handling;
- FastAPI health, latest-state, feature, and score endpoints;
- requirement-level tests for ingestion, replay, windowing, privacy, and fusion behavior.

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

The raw replay archive is written to the `raw-data` volume. Neo4j, Qdrant, and MLflow remain
available through the `intelligence` profile for later phases.

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

## Architecture Docs

- [Domain Model](docs/architecture/domain-model.md)
- [Service Map](docs/architecture/service-map.md)
- [Demo Scenario](docs/architecture/demo-scenario.md)
- [Scope Reset](docs/architecture/scope-reset.md)
- [Architecture Decision Records](docs/architecture/decisions)
- [Phases 2-5 Implementation](docs/implementation/phases-2-5.md)
