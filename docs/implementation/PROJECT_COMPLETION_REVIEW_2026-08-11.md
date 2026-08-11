# Scam2Market Backend Completion Review

> Historical review snapshot: the Phase 9-12 gaps recorded below were subsequently implemented.
> Use [the Phase 9-10 report](PHASE_9_10_IMPLEMENTATION_REPORT.md) and
> [the Phase 11-12 report](PHASE_11_12_IMPLEMENTATION_REPORT.md) for current status. The Phase 8
> official-source connector and analyst verification-view reminder remains open.

Review date: 2026-08-11
Canonical project: `C:\SideQuest\Scam2Market`
Reviewed branch: `work/phase-6-8-review-corrections`

## Executive Summary

The backend is operational as a deterministic local pump-and-dump surveillance demo. The full
default and intelligence Docker stacks run, the API and auxiliary services respond, and a fresh
synthetic replay was observed end to end through ingestion, event-time features, fusion scoring,
campaign creation, alerts, narrative clustering, graph projection, and claim verification.

The most accurate completion boundary is:

- Phases 0-7 are complete for the selected hackathon/demo scope.
- Phase 8's deterministic verification engine is working, but its official-source integrations and
  analyst-facing verification evidence are incomplete.
- Phase 9 is mostly unimplemented, with only an isolated explainability prototype and persistence
  scaffolding.
- Phase 10 is partially implemented: deterministic replay works, while evaluation and MLOps do not.
- Phase 11 has isolated prototypes but is not production-hardened.
- Phase 12 has a working local demo but not a frozen product API, deployment, or analyst workflow.

This distinction matters: the repository is a strong working detection backend, but it is not yet a
complete analyst product or production-shaped platform.

## Verification Results

### Quality Gates

| Gate | Result |
|---|---|
| Ruff format check | Passed, 112 files formatted |
| Ruff lint | Passed |
| MyPy strict check | Passed, 102 source/test files |
| Pytest | Passed, 59 tests |
| Alembic upgrade to head | Passed on disposable TimescaleDB |
| Alembic downgrade one revision | Passed on disposable TimescaleDB |
| Alembic re-upgrade | Passed, `0007_phase_6_9_schema_alignment` at head |
| Docker Compose validation | Passed |
| Backend image build | Passed |

The migration round trip was intentionally executed against a disposable database. Downgrading
`0007` against the persistent development database can collapse enriched score revisions to the
legacy uniqueness contract and would therefore risk deleting development records.

### Running Services

The following services were started and verified:

- TimescaleDB/PostgreSQL: healthy;
- Redis: healthy;
- Redpanda: healthy, with all 17 required topics;
- Neo4j: healthy;
- Qdrant: healthy;
- MLflow: HTTP 200;
- primary FastAPI API: healthy on port 8000;
- explainability API: healthy on port 8001;
- threat-feed API: healthy on port 8002;
- feature, intelligence, campaign, outbox, realtime, archive, telemetry, narrative, verification,
  explainability, and threat-feed workers: running.

### Live Runtime Tests

- Main API health returned `status=ok`.
- Explainability API returned a deterministic fallback explanation.
- Threat-feed API returned successfully with an empty list because no OTX credential is configured.
- A labeled event published to Redis was received through the live WebSocket endpoint.
- The evidence endpoint returned a dominant narrative, graph snapshot, graph features, and graph score.

### End-To-End Replay Evidence

Replay session `bcf2758f-e789-4be4-a22a-37b7ac2af269` completed with:

| Pipeline output | Count |
|---|---:|
| Input market events reported by scheduler | 26 |
| Input social events reported by scheduler | 6 |
| Persisted market trades | 16 |
| Persisted social posts | 6 |
| Feature windows | 13 |
| Model score revisions | 59 |
| Campaigns | 1 |
| Alerts | 5 |
| Narratives | 10 |
| Graph snapshots | 16 |
| Claim verifications | 16 |

The resulting `S2MUSDT` campaign reached `MARKET_PUMP` with HIGH severity. It exposed social hype,
coordinated promotion, market volume, market price, and cross-domain manipulation alerts. No fatal
pipeline errors were logged for the replay.

## Corrections Completed During Verification

- Resolved the Ruff formatting/lint failure reported by CI.
- Resolved strict MyPy errors across threat-feed, explainability, policy, monitoring, security, and
  worker modules.
- Corrected outdated fusion, realtime, claim-verification, and threat-feed tests.
- Added missing runtime dependencies for NumPy and Prometheus client support.
- Added migration `0007_phase_6_9_schema_alignment` for reviewed Phase 6-9 model fields,
  `threat_indicators`, and `explainability_outputs`.
- Made migration `0007` upgrade/downgrade safe for fresh CI databases and enriched score revisions.
- Made the intelligence worker tolerate legacy verification events without
  `verification_snapshot_id`, using canonical `event_id` as a stable fallback.
- Added missing module entrypoints so threat-feed and explainability workers remain alive under
  their Compose commands.
- Added focused worker compatibility tests.
- Rebuilt stale Phase 7-8 images and verified narrative/verification workers against current schema.

## Phase Status

| Phase | Status | Confidence |
|---|---|---|
| 0. Product reset and architecture lock | Complete | High |
| 1. Foundation, infrastructure, contracts | Complete for local/dev | High |
| 2. Market ingestion and replay | Complete for synthetic demo | High |
| 3. Social ingestion and asset resolution | Complete for replay demo | High |
| 4. Feature windows and online state | Complete, checkpoint optimization deferred | High |
| 5. Baseline detectors and fusion | Complete baseline, calibration deferred | High |
| 6. Campaign and alert engine | Core complete, product API partial | High |
| 7. Narrative, embeddings, coordination graph | Complete deterministic baseline | High |
| 8. Disclosure and claim verification | Partially complete | Medium-High |
| 9. Evidence, explanations, analyst workflow | Mostly remaining | High |
| 10. Replay, evaluation, MLOps | Partially complete | High |
| 11. Reliability, security, hardening | Early scaffolding only | High |
| 12. Final dashboard contract and deployment | Partially complete | High |

## Detailed Phase Review

### Phase 0: Complete

Completed:

- marketplace scope removed from the active backend architecture;
- pump-and-dump domain model documented;
- seven architecture decision records exist for FastAPI, Redpanda, TimescaleDB, event time, Neo4j,
  Qdrant, and the modular monolith;
- service map and deterministic demo scenario documented;
- phased implementation plan established.

No blocking Phase 0 work remains.

### Phase 1: Complete For Local Development

Completed:

- FastAPI application, worker entrypoints, Pydantic contracts, SQLAlchemy, and Alembic;
- TimescaleDB/PostgreSQL, Redis, Redpanda, Neo4j, Qdrant, and MLflow Compose services;
- canonical event envelope and versioned topic catalog;
- JSON logging, request/correlation middleware, settings validation, error classes, and CI workflow;
- foundation/control-plane tables and migration chain;
- successful image build, topic initialization, and service health validation.

Deferred to Phase 11:

- production secret management;
- production health/readiness probes for every worker;
- full telemetry and operational dashboards.

### Phase 2: Complete For The Selected Demo

Completed:

- market provider interface, deterministic replay provider, and synthetic pump provider;
- normalized trades, candles, and order-book snapshots;
- event-time handling, Redis and database deduplication, sequence-gap/quality states, and freshness;
- Timescale persistence, latest-state API, and immutable Parquet archive;
- required market features and replay tests.

Deferred:

- live Binance or exchange adapter;
- cloud object storage implementation and retention policy;
- production reconnect/rate-limit handling against a live exchange.

### Phase 3: Complete For The Selected Demo

Completed:

- social provider interface and deterministic replay provider;
- stable versioned HMAC author pseudonyms;
- hashtag, cashtag, URL, mention, repost, and reply parsing;
- versioned asset registry/resolver with explicit ambiguity handling;
- normalized social persistence, mention queries, freshness, and social feature inputs.

Deferred:

- live social/news provider connectors and their legal/rate-limit policies;
- key rotation backed by a secrets manager rather than development configuration.

### Phase 4: Complete With One Scalability Deferral

Completed:

- event-time 1-minute and 5-minute windows;
- watermarks, allowed lateness, provisional/final/corrected revisions;
- immutable feature history, lineage hashes, schema manifest/hash validation, and Redis latest state;
- market, social, temporal, quality, and baseline-confidence feature groups;
- deterministic replay output.

Deferred:

- durable rolling-state snapshots for the feature worker. It currently rebuilds feature state from
  retained events after restart. This is correctness-oriented but will not scale to long retention.

### Phase 5: Complete Baseline

Completed:

- market anomaly, social surge, coordination, and lead/lag detectors;
- market regime and liquidity classification;
- optional peer-relative context;
- versioned fusion, explicit missing outputs, confidence degradation, and severity thresholds;
- social-only hype cannot create a critical cross-domain alert without market evidence;
- graph/verification enrichment revisions have stable idempotency identities.

Deferred:

- statistically calibrated probabilities based on labeled data;
- production model artifact loading and registry integration;
- evaluated cross-asset peer groups at meaningful data scale.

### Phase 6: Core Complete, API Contract Partial

Completed:

- campaign state machine, merge windows, persistence, optimistic/pessimistic concurrency controls;
- evidence idempotency, alert taxonomy, suppression, severity history, and transactional outbox;
- Redis Stream-based SSE and WebSocket delivery with reconnect cursors;
- live replay produced one campaign and five stable alerts;
- live WebSocket delivery was verified.

Remaining:

- alert list is not filtered by `scope_id`, so replay alerts appear in the default alert list;
- campaign detail, alert detail, acknowledgment, and asset timeline endpoints are missing;
- alert/campaign authorization and analyst ownership are not implemented;
- API contracts need stable response schemas instead of generic dictionaries.

### Phase 7: Complete Deterministic Baseline

Completed:

- deterministic hash embeddings and Qdrant metadata indexing;
- replay-stable clustering, narrative revisioning, labels, summaries, and memberships;
- Neo4j graph projection and required graph feature calculations;
- graph cutoff/lineage/component status persistence;
- baseline continues when graph infrastructure is unavailable;
- live replay produced narratives, Neo4j projections, graph snapshots, and graph-enriched scores.

Deferred:

- production semantic embedding model and model/version lifecycle;
- richer graph analytics over longer history and cross-campaign actor identity;
- dedicated narrative and graph REST endpoints.

### Phase 8: Partially Complete

Completed:

- disclosure schemas, chunking, persistence, and time-bounded retrieval architecture;
- deterministic claim extraction and five verification outcomes;
- future-document leakage protection and retrospective-only classification;
- verification evidence metadata and fusion claim/legitimate-event inputs;
- live replay produced 16 claim verification records.

Remaining:

- no production connector for official disclosures or reliable news sources;
- the campaign evidence API does not expose claim verification status/evidence, so the Phase 8 exit
  criterion is not fully met in the analyst-facing contract;
- no dedicated claim/disclosure/verification API;
- no evidence-bounded LLM summary provider;
- source policy governance and source-quality administration remain configuration-only.

### Phase 9: Mostly Remaining

Existing scaffolding:

- isolated explainability API with deterministic fallback feature ranking;
- `explainability_outputs` persistence model/table;
- campaign evidence and graph evidence already provide useful inputs.

Not complete:

- explainability worker does not consume a broker topic and is explicitly a placeholder;
- explanations are kept in process memory by the API and are not linked to alerts;
- no immutable `evidence_snapshots` or complete alert evidence bundle;
- no investigation, investigation-event, analyst-feedback, or raw-access audit workflows;
- no deterministic alert explanation containing every required market/social/graph/verification field;
- no tests proving every HIGH/CRITICAL alert has a complete evidence snapshot.

### Phase 10: Partially Complete

Completed:

- tracked replay sessions and deterministic synthetic scenario manifest;
- replay/live scope isolation;
- full local replay that reaches campaign, alert, graph, and verification output;
- MLflow container starts successfully.

Not complete:

- no replay control API, virtual-clock pause/resume, or configurable speed controls;
- no evaluation tables/services or detection lead-time report;
- no hard-negative precision/false-positive report;
- no required detector ablation runner;
- MLflow is not connected to score production, artifacts, hashes, aliases, or input contracts;
- no candidate/champion or shadow scoring workflow.

### Phase 11: Early Scaffolding Only

Existing scaffolding:

- structured JSON logs and common correlation fields;
- source-health/freshness calculations;
- standalone Prometheus model-monitor prototype;
- standalone Redis rate-limiter prototype;
- OTX threat-feed API/worker and persistence table;
- Compose restart policies for core long-running workers.

Not complete:

- model monitor, policy proposal service, and rate limiter are not integrated into Compose/main API;
- threat-feed ingestion requires `OTX_API_KEY` and currently runs in a visible degraded loop without it;
- no OpenTelemetry pipeline, Grafana dashboard, circuit-breaker framework, backpressure policy, or
  micro-batching;
- no secrets manager, production credential rotation, prompt-injection controls, or data-poisoning
  guardrails;
- required component-failure integration tests are missing;
- no backup/restore runbook or production readiness probes.

### Phase 12: Partially Complete

Completed:

- Docker-based local environment;
- one-command deterministic replay command;
- core API, evidence view, realtime delivery, and README instructions;
- a successful full local demonstration.

Not complete:

- API surface is not frozen and several planned endpoints are absent;
- no watchlist, timeline, alert detail/acknowledgment, narrative detail, replay control, evaluation,
  investigation, or feedback APIs;
- no frontend/dashboard contract package or generated client schema;
- no deployment environment, infrastructure-as-code, or hosted demo;
- no single integration test in CI that boots the complete Compose stack and runs the replay;
- known limitations are not yet consolidated into release documentation.

## Priority Plan From Here

### Next: Phase 9 Completion

1. Define immutable `EvidenceSnapshot` and `AlertEvidence` contracts.
2. Persist an evidence snapshot atomically with every HIGH/CRITICAL alert.
3. Include feature lineage, score identity, thresholds, campaign transition reason, narrative/graph
   evidence, freshness, and claim verification evidence.
4. Replace the standalone explainability prototype with an alert-linked deterministic explanation
   service and broker worker.
5. Add investigation, investigation event, analyst feedback, and sensitive-access audit tables/APIs.
6. Add completeness, immutability, linkage, and access-audit tests.

### Then: Phase 10 Completion

1. Add replay create/start/status APIs and persisted replay configuration.
2. Implement evaluation metrics and hard-negative datasets.
3. Implement required ablations and compare outputs reproducibly.
4. Integrate MLflow artifacts, feature-contract hashes, aliases, and lineage.
5. Add shadow scoring that cannot control campaign or alert state.

### Then: Phase 11 Hardening

1. Integrate OpenTelemetry and Prometheus into every service.
2. Add Grafana and operational dashboards.
3. Add retries/circuit breakers, backpressure, batch policies, and failure tests.
4. Replace development secrets, isolate credentials, and add security controls.
5. Add backup/recovery and readiness/runbook documentation.

### Finally: Phase 12 Contract And Release

1. Complete and freeze the analyst-facing API.
2. Generate OpenAPI client contracts for the dashboard.
3. Add a complete Compose replay regression to CI.
4. Prepare a hosted or reproducible local demo release.
5. Publish known limitations and deferred production work.

## Immediate Repository Actions

- Review and commit the current working tree; the verified corrections are not yet committed.
- Push the branch and confirm GitHub Actions passes.
- Fix replay scope filtering in the alert list before dashboard integration.
- Update `/api/v1/config`, which still reports `phase-5-baseline-fusion` despite Phase 6-8 runtime
  availability.
- Add `OTX_API_KEY` through a local secret when threat-feed ingestion is desired; do not add it to
  `.env.example` or commit it.

## Current Local URLs

- Main API/OpenAPI: `http://localhost:8000/docs`
- Explainability prototype: `http://localhost:8001/docs`
- Threat-feed API: `http://localhost:8002/docs`
- Neo4j browser: `http://localhost:7474`
- Qdrant: `http://localhost:6333`
- MLflow: `http://localhost:5000`
