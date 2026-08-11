# Scam2Market Phases 9-10 Implementation Report

Implementation date: 2026-08-11
Canonical project: `C:\SideQuest\Scam2Market`
Database revision: `0008_phase_9_10`

## Outcome

Phase 9 and the previously missing Phase 10 evaluation/MLOps capabilities are implemented and
verified in the running Docker intelligence stack. The implementation preserves replay isolation,
uses deterministic identities for reproducibility, and prevents shadow models from influencing
campaign or alert state.

## Phase 8 Reminder

The deterministic verification engine is working. Complete these remaining Phase 8 items before
calling the phase production-ready:

- production connectors for official disclosures and reliable news;
- source-policy administration and connector health monitoring;
- dedicated analyst APIs for claims, disclosures, retrieval evidence, and verification timelines;
- evidence-bound optional LLM summaries with strict citation and event-time constraints.

## Phase 9 Completed

### Immutable Evidence Ledger

- `evidence_snapshots` stores a complete point-in-time alert bundle.
- Canonical JSON SHA-256 content hashes make snapshots content-addressable.
- Per-alert chain hashes provide ordered chain-of-custody evidence.
- PostgreSQL triggers reject update and delete operations on snapshots, evidence references, and
  deterministic explanations.
- `alert_evidence` stores independently hashed feature, campaign, narrative, graph, and claim
  verification references.
- Completeness scoring explicitly reports present and missing evidence domains.
- The evidence worker consumes `alerts.events.v1`, is idempotent by alert/version, and backfills
  queued alerts safely.

### Explainability

- Explanations are linked to immutable snapshots instead of process memory.
- Output includes triggered rules, ordered contributors, market corroboration, campaign stage,
  evidence cutoff, model/fusion/threshold versions, lead-lag context, narrative counts, graph
  context, verification outcomes, and completeness.
- Optional LLM output is explicitly represented as `NOT_REQUESTED` or unavailable; deterministic
  explanations do not depend on an LLM.

### Analyst Workflow

- Investigations support scope isolation, assignment, priority, tags, optimistic versioning, SLA
  deadlines, status, and disposition.
- Append-only investigation events preserve the analyst timeline.
- Analyst feedback supports five labels, confidence, rationale, and second-review adjudication.
- Evidence manifest access requires actor and reason headers and writes to `audit_logs`.
- Model registration and alias changes also create governance audit records.

### Additional Phase 9 Features

- evidence completeness scoring;
- cryptographic chain-of-custody hashes;
- exportable evidence manifests;
- SLA breach calculation;
- feedback adjudication rather than unreviewed labels;
- optimistic investigation concurrency control;
- replay-aware scope isolation throughout evidence and investigation APIs.

## Phase 10 Completed

### Replay Evaluation

- Replay sessions now persist scope, scenario version, manifest hash, seed, virtual-clock state,
  requested owner, configuration, isolation policy, and failure reason.
- Evaluation is deterministic and idempotent by replay, evaluator version, and manifest hash.
- Metrics include observation/alert counts, first WATCH/HIGH/CRITICAL timestamps, detection lead
  time, hard-negative precision proxy, false-positive rate, confidence, missing-output rate, p50/p95
  processing latency, source freshness, and peak score.

### Ablations

The evaluator persists five cumulative, reproducible profiles:

1. `MARKET_ONLY`
2. `MARKET_SOCIAL`
3. `COORDINATION`
4. `GRAPH`
5. `VERIFICATION`

Each result stores its exact component set, full metrics, and incremental peak-score contribution.

### MLOps And Shadow Scoring

- Evaluations are logged to MLflow through its REST API.
- MLflow is configured with a restricted host allowlist for internal API and localhost access.
- Model artifacts store family/version, URI, artifact hash, input-contract hash, training-data hash,
  MLflow run, and metadata.
- Governed aliases support `CHAMPION`, `CANDIDATE`, and `SHADOW`, with reason and actor auditing.
- Shadow fusion uses versioned artifact weights and records agreement, confidence, and latency.
- A database check constraint enforces `controls_alerts = false` for every shadow score.

## API Surface

Evidence and investigations:

- `GET /api/v1/alerts/{alert_id}/evidence`
- `GET /api/v1/alerts/{alert_id}/explanation`
- `GET /api/v1/evidence/{snapshot_id}/manifest`
- `POST /api/v1/investigations`
- `GET /api/v1/investigations`
- `PATCH /api/v1/investigations/{investigation_id}`
- `POST /api/v1/investigations/{investigation_id}/events`
- `POST /api/v1/investigations/{investigation_id}/feedback`
- `POST /api/v1/feedback/{feedback_id}/adjudicate`

Replay and model governance:

- `POST /api/v1/replays`
- `GET /api/v1/replays`
- `GET /api/v1/replays/{replay_session_id}`
- `POST /api/v1/replays/{replay_session_id}/evaluate`
- `POST /api/v1/models/artifacts`
- `PUT /api/v1/models/{model_family}/aliases/{alias}`
- `POST /api/v1/shadow-scores`

## Verification Evidence

| Check | Result |
|---|---|
| Ruff formatting | Passed, 127 files |
| Ruff lint | Passed |
| MyPy strict | Passed, 116 source/test files |
| Pytest | Passed, 64 tests |
| Fresh migration upgrade | Passed on isolated TimescaleDB |
| Latest migration downgrade/re-upgrade | Passed |
| Evidence worker | Stable; 11 queued alert snapshots backfilled during verification |
| Evidence immutability | PostgreSQL rejected a direct snapshot update |
| Evidence/explanation APIs | Passed against a replay alert |
| Investigation/feedback/adjudication | Passed end to end |
| Replay evaluation | 244 score observations evaluated |
| Ablations | All five profiles persisted |
| MLflow | Evaluation run ID persisted successfully |
| Model artifact and candidate alias | Passed with audit record |
| Shadow scoring | Passed; `controls_alerts=false`, agreement recorded |
| Full Docker intelligence profile | All services running; infrastructure healthy |

## Remaining Boundaries

- Replay create/list configuration APIs exist, while durable API-triggered start/pause/resume
  command orchestration remains a Phase 11 reliability enhancement. The existing scheduler remains
  the execution path.
- Evaluation labels are derived from the deterministic scenario manifest; production evaluation
  requires curated labeled datasets and approved hard-negative suites.
- Processing latency reflects persisted pipeline timing. Dedicated per-detector timers should be
  added with OpenTelemetry in Phase 11.
- The older standalone explainability prototype remains available for compatibility, but the
  evidence-linked Phase 9 explanation is the authoritative analyst output.
