# Scam2Market Backend Phase Distribution

Date: 2026-08-08

Source reviewed:

- `C:\SideQuest\Finance\Scam2Market_Backend_Advanced_Implementation_Review.md`
- Existing repo plan: `BACKEND_IMPLEMENTATION_PLAN.md`

## 1. Corrected Backend Direction

The review changes the backend direction completely. Scam2Market should not be implemented as a buyer/seller scam-report marketplace. The correct product is:

> A real-time AI market-surveillance backend that detects possible pump-and-dump campaigns by correlating market anomalies, social manipulation, temporal signals, graph coordination, narrative activity, claim verification, and analyst feedback.

The previous plan's useful engineering patterns should be retained:

- modular monolith structure;
- PostgreSQL as system of record;
- Redis for online state, cache, dedupe, and rate limits;
- event-driven processing;
- idempotent ingestion;
- transactional outbox where database updates publish downstream events;
- auditability;
- background workers;
- structured observability;
- Docker-based local and demo deployment;
- API versioning;
- correlation IDs;
- human review for high-impact AI output.

The following previous modules should be removed from core scope:

- marketplace listings;
- buyer/seller flows;
- Stripe Connect;
- checkout, commissions, payouts, escrow, and refunds;
- marketplace reviews;
- buyer/seller messaging;
- marketplace disputes;
- seller trust scoring.

## 2. Final Build Objective

The backend is complete for the hackathon when it can run this end-to-end flow:

1. Start a replay session.
2. Market and social events enter the same event pipeline.
3. Events are normalized, deduplicated, timestamped by event time, and persisted.
4. Rolling 1-minute and 5-minute feature windows update.
5. Market and social baseline detectors generate scores.
6. Narrative clustering and coordination signals appear.
7. Graph projection strengthens the evidence.
8. Disclosure/claim verification checks whether the hype is supported by official information.
9. A calibrated fusion score crosses WATCH, HIGH, or CRITICAL.
10. A campaign is created or updated.
11. An alert is emitted through WebSocket/SSE.
12. Evidence snapshots explain the alert.
13. Analyst investigation and feedback are recorded.
14. Replay evaluation reports detection lead time and false-positive behavior.

## 3. Recommended Backend Stack

| Layer | Decision |
|---|---|
| API framework | FastAPI |
| Language | Python 3.12+ |
| Validation | Pydantic |
| ORM and migrations | SQLAlchemy 2 + Alembic |
| Time-series database | PostgreSQL + TimescaleDB |
| Online state/cache/dedupe | Redis |
| Streaming broker | Redpanda |
| Graph intelligence | Neo4j |
| Vector retrieval | Qdrant |
| Data processing | Polars |
| Baseline ML | scikit-learn + LightGBM/XGBoost |
| Deep learning experiments | PyTorch |
| Graph ML experiments | PyTorch Geometric |
| Model tracking | MLflow |
| Observability | OpenTelemetry + Prometheus + Grafana |
| Deployment | Docker Compose for hackathon; containerized services for demo cloud |
| Frontend transport | REST + WebSocket/SSE |

## 4. Phase Gates

These gates control when the team is allowed to move into more advanced work.

| Gate | Name | Must Pass Before |
|---|---|---|
| Gate A | Data Correctness | Any advanced AI, graph scoring, or final demo work |
| Gate B | Detection Baseline | Graph/verification polish and advanced models |
| Gate C | Explainability | Final judging/demo readiness |
| Gate D | Advanced AI | Only after A, B, and C are working |

### Gate A: Data Correctness

Pass criteria:

- market replay produces canonical events;
- social replay produces canonical events;
- duplicate events do not double-count;
- event time, ingestion time, and processing time are stored separately;
- 1-minute and 5-minute windows are computed by event time;
- late events are handled with revisioned windows;
- replay output is deterministic for the same dataset and replay speed;
- raw events can be traced to feature windows.

### Gate B: Detection Baseline

Pass criteria:

- market-only baseline score exists;
- social-only baseline score exists;
- coordination baseline score exists;
- fusion baseline combines market, social, temporal, and coordination signals;
- score calibration is documented;
- missing-model behavior is explicit and does not silently bias risk;
- WATCH/HIGH/CRITICAL thresholds are configurable.

### Gate C: Explainability

Pass criteria:

- every alert has immutable/revisioned evidence;
- every alert links to source events, feature snapshots, model versions, and thresholds;
- deterministic explanation works even if LLM explanation fails;
- analyst can inspect timeline, campaign, evidence graph, narrative, and claim-verification result.

### Gate D: Advanced AI

Pass criteria:

- baseline system is already demoable;
- model input contracts are tested;
- MLflow records model versions;
- candidate/champion model workflow exists;
- shadow-mode scoring can run without controlling alerts;
- hard-negative replay scenarios are evaluated.

## 5. Four-Week Phase Distribution

This distribution is designed for a 20-working-day hackathon build. Each phase is scoped to produce a demoable backend increment.

## Phase 0: Product Reset And Architecture Lock

Duration: 0.5-1 day.

Goal:

Replace the marketplace interpretation with the correct pump-and-dump intelligence architecture before any implementation starts.

Deliverables:

- final backend domain model;
- architecture decision records for Python/FastAPI, Redpanda, TimescaleDB, event time, Neo4j projection, Qdrant RAG, and modular monolith;
- removed marketplace/payment/listing/dispute scope from backend backlog;
- service map for API, market ingestor, social ingestor, stream worker, intelligence worker, graph worker, verification worker, and replay scheduler;
- first demo scenario selected.

Core domain objects:

- `Asset`
- `MarketTrade`
- `MarketCandle`
- `OrderBookUpdate`
- `SocialPost`
- `AssetMention`
- `Disclosure`
- `FeatureWindow`
- `Narrative`
- `GraphSnapshot`
- `ModelScore`
- `Campaign`
- `Alert`
- `EvidenceSnapshot`
- `Investigation`
- `ReplaySession`

Exit criteria:

- no marketplace modules remain in the core backend plan;
- exact 20-day build sequence is agreed;
- team knows the dataset/replay source for the demo.

## Phase 1: Foundation, Infrastructure, And Contracts

Duration: Days 1-2.

Goal:

Create the backend skeleton and contracts needed for a reliable event-time surveillance pipeline.

Implementation work:

- scaffold FastAPI app;
- create worker entrypoints;
- create shared Pydantic schema package;
- add SQLAlchemy 2 and Alembic;
- add PostgreSQL + TimescaleDB;
- add Redis;
- add Redpanda;
- add optional Neo4j, Qdrant, and MLflow containers but keep them non-blocking until later phases;
- configure Docker Compose;
- add environment validation;
- add JSON structured logging;
- add request IDs and correlation IDs;
- define error taxonomy;
- create initial CI commands for lint, type-check, tests, migration checks, and Docker build.

Canonical event envelope must include:

- `event_id`
- `event_type`
- `schema_version`
- `source`
- `source_event_id`
- `source_sequence`
- `asset_id`
- `event_time`
- `ingested_at`
- `processed_at`
- `partition_key`
- `replay.is_replay`
- `replay.replay_session_id`
- `trace.correlation_id`
- `trace.causation_id`
- `payload`

Initial Redpanda topics:

- `market.trades.v1`
- `market.candles.v1`
- `market.orderbook.v1`
- `social.posts.raw.v1`
- `social.posts.normalized.v1`
- `social.mentions.v1`
- `disclosures.documents.v1`
- `features.market.v1`
- `features.social.v1`
- `model.fusion.score.v1`
- `campaign.events.v1`
- `alerts.events.v1`
- `deadletter.ingestion.v1`
- `deadletter.inference.v1`

Database tables:

- `assets`
- `data_sources`
- `replay_sessions`
- `event_ingestion_log`
- `schema_versions`
- `system_config`
- `audit_logs`

Tests:

- event schema validation;
- schema compatibility smoke test;
- migration test;
- Docker Compose service health test.

Exit criteria:

- API boots locally;
- database migrations run cleanly;
- Redpanda topics can be created;
- test event can be validated and published.

## Phase 2: Market Ingestion And Replay

Duration: Days 2-4.

Goal:

Build deterministic market ingestion before any AI or graph work.

Implementation work:

- define `MarketProvider` interface;
- implement `ReplayProvider`;
- implement `SyntheticProvider` for controlled demo events;
- optionally implement `BinanceProvider` if live feed is required;
- normalize trades, candles, and top-of-book/orderbook snapshots;
- write raw immutable market events to object storage or local Parquet for hackathon mode;
- persist normalized market events to TimescaleDB;
- implement event-time assignment;
- implement deduplication using Redis plus persistent uniqueness where needed;
- detect source sequence gaps and feed freshness;
- add market source health endpoint.

TimescaleDB tables:

- `market_trades`
- `market_candles`
- `orderbook_snapshots`
- `orderbook_features`

Required market features:

- price return;
- volume;
- relative volume;
- volatility;
- spread;
- top-N depth;
- orderbook imbalance;
- trade count;
- buy/sell pressure if side is available;
- market data freshness.

Tests:

- duplicate trade does not double-count;
- replay emits deterministic event count;
- event-time order is preserved per asset partition;
- source gap creates degraded data-quality state;
- delayed event is stored with correct event time.

Exit criteria:

- replayed market data enters Redpanda;
- normalized market data persists in TimescaleDB;
- latest market state is available through Redis/API.

## Phase 3: Social Ingestion And Asset Resolution

Duration: Days 3-5.

Goal:

Build the social-to-asset pipeline, including ambiguity handling.

Implementation work:

- define `SocialProvider` interface;
- implement social replay provider from dataset;
- normalize social posts;
- pseudonymize author IDs;
- parse hashtags, cashtags, URLs, and mentions;
- implement canonical asset registry;
- implement asset mention candidate extraction;
- add ambiguity scoring for symbols like `ONE`, `LINK`, `NEAR`, and `CAT`;
- store mention confidence and resolver version;
- write raw social data to Parquet/object storage;
- persist normalized posts and mentions.

Database tables:

- `social_posts`
- `post_asset_mentions`
- `asset_aliases`
- `resolver_versions`

Required social features:

- mention count;
- unique author count;
- author concentration;
- repost/reply ratio;
- hashtag velocity;
- URL concentration;
- new-author ratio;
- social data freshness.

Tests:

- ambiguous symbols are not silently mapped;
- replayed posts produce stable post IDs;
- duplicate social posts do not double-count;
- asset mentions include confidence and resolver version;
- pseudonymous actor ID is stable but does not expose raw identity.

Exit criteria:

- social replay enters Redpanda;
- social posts normalize correctly;
- asset mentions are queryable;
- market and social streams can be correlated by asset and event time.

## Phase 4: Feature Windows And Online State

Duration: Days 4-6.

Goal:

Create reproducible online/offline features for model input.

Implementation work:

- build rolling 1-minute and 5-minute feature windows;
- compute windows using event time, not ingestion time;
- add allowed lateness configuration;
- mark windows as provisional/final;
- create feature revisioning when late events alter a window;
- persist feature snapshots;
- store latest asset features in Redis;
- create feature schema versioning;
- create baseline confidence for newly listed or low-history assets.

Database tables:

- `feature_windows`
- `feature_revisions`
- `feature_lineage`
- `asset_baselines`

Required feature groups:

- market features;
- social features;
- temporal lead/lag features;
- data quality features;
- baseline confidence features.

Tests:

- late event revises affected feature window;
- finalized windows remain reproducible;
- feature snapshot includes lineage;
- model input schema rejects missing or reordered features;
- Redis latest state matches latest persisted feature snapshot.

Exit criteria:

- Gate A is mostly satisfied;
- dashboard/API can read latest features per asset;
- replay can regenerate identical features for the same input.

## Phase 5: Baseline Detectors And Fusion V1

Duration: Days 6-9.

Goal:

Create the first real detection system before adding heavier graph or LLM components.

Implementation work:

- implement market anomaly detector;
- implement social surge detector;
- implement temporal lead/lag detector;
- implement initial coordination heuristics;
- implement market regime engine;
- implement asset liquidity class;
- implement cross-asset context baseline if peer data is available;
- implement fusion v1 with configurable weights;
- add calibrated score output when enough data exists;
- explicitly represent missing detector outputs;
- create threshold configuration for NORMAL, WATCH, HIGH, and CRITICAL.

Scores:

- `market_score`
- `social_score`
- `coordination_score`
- `temporal_score`
- `claim_risk`
- `legitimate_event_score`
- `fusion_score`
- `confidence`

Database tables:

- `model_scores`
- `threshold_configs`
- `market_regimes`
- `asset_liquidity_classes`

Tests:

- market-only detector flags abnormal volume/price;
- social-only detector flags mention velocity;
- fusion does not create CRITICAL from social hype alone;
- degraded market/social data lowers confidence;
- missing model output is visible and handled safely.

Exit criteria:

- Gate B passes for baseline detection;
- replay can show simple risk score rising before or during a pump scenario;
- false-positive hard-negative scenarios can be replayed.

## Phase 6: Campaign And Alert Engine

Duration: Days 9-11.

Goal:

Turn repeated scores into stable campaign state and useful alerts instead of noisy one-off warnings.

Implementation work:

- create campaign state machine;
- implement campaign merge logic;
- implement campaign persistence across windows;
- implement alert taxonomy;
- implement alert suppression;
- implement alert persistence rules;
- implement idempotent alert creation;
- add concurrency control for campaign updates;
- publish campaign/alert events through outbox;
- create WebSocket/SSE stream.

Campaign stages:

- `NORMAL`
- `EARLY_SOCIAL_SEEDING`
- `COORDINATED_AMPLIFICATION`
- `MARKET_PUMP`
- `DISTRIBUTION`
- `DUMP`
- `POST_EVENT`

Alert taxonomy:

- `SOCIAL_HYPE_SURGE`
- `COORDINATED_PROMOTION`
- `UNVERIFIED_NARRATIVE`
- `MARKET_VOLUME_ANOMALY`
- `MARKET_PRICE_ANOMALY`
- `MARKET_MICROSTRUCTURE_ANOMALY`
- `CROSS_DOMAIN_MANIPULATION_RISK`
- `POSSIBLE_DUMP_PHASE`

Database tables:

- `campaigns`
- `campaign_stage_history`
- `alerts`
- `alert_state_history`
- `outbox_events`

Tests:

- same evidence does not create duplicate alerts;
- campaign stage transition is valid;
- alert severity changes are recorded;
- two workers updating one campaign do not corrupt state;
- WebSocket/SSE receives alert event.

Exit criteria:

- coordinated social surge plus market anomaly creates or updates a campaign;
- alert appears in real time;
- demo flow can show risk moving from NORMAL to WATCH/HIGH.

## Phase 7: Narrative, Embeddings, And Coordination Graph

Duration: Days 11-13.

Goal:

Add graph and narrative intelligence after the baseline detector already works.

Implementation work:

- generate text embeddings for normalized social posts;
- index embeddings in Qdrant;
- cluster posts by asset/time window using semantic similarity;
- label and summarize narrative clusters;
- project social coordination graph into Neo4j;
- create actor, post, asset, narrative, campaign, and alert nodes;
- create relationships for mentions, reposts, replies, amplification, narrative membership, campaign targeting, and alert evidence;
- run cheap graph analytics first;
- compute graph features for fusion.

Graph features:

- community concentration;
- synchronized posting;
- repeated amplifier overlap;
- propagation depth;
- community entropy;
- time to 10 authors;
- time to 100 authors;
- cross-community spread;
- node similarity or shared URL/hashtag clusters.

Database/storage:

- Qdrant collections for post/narrative embeddings;
- Neo4j graph projection;
- `narratives`
- `narrative_posts`
- `graph_snapshots`
- `graph_features`

Tests:

- embeddings are indexed with asset/time metadata;
- narrative clustering is reproducible for replay;
- graph projection links posts to assets and narratives;
- graph worker failure does not break baseline detection;
- graph score can be missing without corrupting fusion.

Exit criteria:

- analyst can open evidence graph for an alert;
- graph score strengthens or weakens fusion result;
- dominant narrative is visible for a campaign.

## Phase 8: Disclosure And Claim Verification

Duration: Days 13-15.

Goal:

Reduce false positives by checking whether social claims are supported by official disclosures or reliable news within valid time bounds.

Implementation work:

- ingest official disclosures/news datasets;
- normalize disclosure documents;
- index disclosure chunks in Qdrant;
- implement time-bounded retrieval;
- extract claims from narratives;
- verify whether claims had support before the alert time;
- prevent temporal leakage from future documents;
- store verification evidence and retrieval metadata;
- add deterministic claim-verification result into fusion.

Database tables:

- `disclosures`
- `disclosure_chunks`
- `claims`
- `claim_verifications`

Verification outputs:

- `SUPPORTED_BEFORE_ALERT`
- `SUPPORTED_AFTER_ALERT`
- `UNSUPPORTED`
- `CONFLICTING`
- `UNKNOWN`

Tests:

- future disclosure is not used to justify past alert;
- unsupported narrative increases claim risk;
- supported official event reduces manipulation confidence where appropriate;
- retrieval output includes document IDs and timestamps;
- LLM failure does not block deterministic verification result.

Exit criteria:

- Gate C can pass;
- alert explanation includes whether the narrative was officially supported at event time.

## Phase 9: Evidence Engine, Explanations, And Analyst Workflow

Duration: Days 15-16.

Goal:

Make every alert explainable, reviewable, and defensible.

Implementation work:

- create immutable evidence snapshots;
- store feature snapshot IDs and source event ranges;
- store model versions and threshold config with alerts;
- implement deterministic explanation;
- add optional LLM evidence-bounded summary;
- add analyst investigation workflow;
- add analyst feedback loop;
- add access logging for sensitive raw content;
- add audit logs for investigation decisions.

Database tables:

- `alert_evidence`
- `evidence_snapshots`
- `investigations`
- `investigation_events`
- `analyst_feedback`
- `explanations`

Deterministic explanation must include:

- triggered rules;
- top feature contributors;
- lead/lag values;
- narrative counts;
- author/community concentration;
- graph signals;
- data freshness;
- claim verification result;
- model and threshold versions.

Tests:

- every HIGH/CRITICAL alert has evidence;
- explanation works without LLM;
- analyst feedback is linked to campaign and model score;
- evidence is immutable or revisioned;
- raw social content access is logged.

Exit criteria:

- analyst can inspect an alert and understand why it fired;
- feedback can be used later for model evaluation/retraining.

## Phase 10: Replay, Evaluation, And MLOps

Duration: Days 16-18.

Goal:

Prove the backend works with deterministic replay and measurable detection quality.

Implementation work:

- create replay scheduler with virtual clock;
- support replay speed controls;
- isolate replay sessions from live sessions;
- record dataset version and replay configuration;
- create full demo scenario replay;
- implement evaluation metrics;
- implement ablation runs;
- integrate MLflow;
- record model artifacts, hashes, and model input contracts;
- add candidate/champion model aliases;
- add shadow-mode scoring.

Evaluation metrics:

- detection lead time;
- precision proxy on hard-negative scenarios;
- alert count per asset;
- false-positive rate against legitimate event scenarios;
- latency from event time to alert;
- detector ablation contribution;
- data freshness and source health.

Required ablations:

- market only;
- market + social;
- market + social + coordination;
- market + social + graph;
- market + social + graph + verification.

Tests:

- replay is deterministic;
- replay does not pollute live campaign state;
- model input schema mismatch fails closed;
- model artifact hash is recorded;
- shadow model output does not control alerts.

Exit criteria:

- final demo scenario is reproducible;
- backend reports detection lead time;
- model lineage is visible.

## Phase 11: Reliability, Security, And Production-Shaped Hardening

Duration: Days 18-19.

Goal:

Make the system robust enough for a convincing technical demo and future production evolution.

Implementation work:

- add OpenTelemetry traces;
- add Prometheus metrics;
- add Grafana dashboard;
- add circuit breakers for source, graph, retrieval, and model failures;
- add backpressure handling;
- add micro-batching for high-volume event processing;
- add data freshness endpoint;
- add source-health scoring;
- add backup/recovery notes;
- add secrets handling;
- add prompt-injection and data-poisoning guardrails;
- add structured JSON logging fields.

Required logging fields:

- `timestamp`
- `service`
- `level`
- `event_type`
- `request_id`
- `correlation_id`
- `asset_id`
- `campaign_id`
- `replay_session_id`
- `model_version`
- `latency_ms`

Failure tests:

- Redpanda temporarily unavailable;
- Redis unavailable;
- Neo4j unavailable;
- Qdrant unavailable;
- model artifact missing;
- late event burst;
- duplicate event burst;
- invalid event schema;
- source feed degraded.

Exit criteria:

- backend degrades visibly and safely;
- errors use stable error taxonomy;
- final demo can survive non-critical component failure.

## Phase 12: Final Dashboard Contract, Demo, And Deployment

Duration: Day 20.

Goal:

Freeze the API contract and produce a working end-to-end demo.

Implementation work:

- finalize REST endpoints;
- finalize WebSocket/SSE event payloads;
- create seed/demo data;
- create one-command replay start;
- create final demo script;
- run full replay regression;
- run integration tests;
- deploy demo backend or prepare local demo environment;
- document known limitations and deferred work.

Final demo API areas:

- watchlist;
- asset intelligence;
- timeline;
- campaign detail;
- alert detail;
- evidence graph;
- narratives;
- explanation;
- replay control;
- investigation and feedback.

Exit criteria:

- final backend can run the full scenario listed in Section 2;
- all hackathon definition-of-done items are either complete or explicitly documented as deferred;
- the system demonstrates originality, technical depth, working detection, and market insight.

## 6. API Distribution By Phase

| API Area | Phase | Endpoints |
|---|---:|---|
| Health/config | 1 | `GET /health`, `GET /api/v1/config`, `GET /api/v1/source-health` |
| Watchlist | 5 | `GET /api/v1/watchlist`, `POST /api/v1/watchlist/assets`, `DELETE /api/v1/watchlist/assets/{asset_id}` |
| Asset intelligence | 5 | `GET /api/v1/assets/{asset_id}/overview`, `GET /api/v1/assets/{asset_id}/features`, `GET /api/v1/assets/{asset_id}/scores` |
| Timeline | 6 | `GET /api/v1/assets/{asset_id}/timeline` |
| Campaigns | 6 | `GET /api/v1/campaigns`, `GET /api/v1/campaigns/{campaign_id}` |
| Alerts | 6 | `GET /api/v1/alerts`, `GET /api/v1/alerts/{alert_id}`, `POST /api/v1/alerts/{alert_id}/acknowledge` |
| Realtime | 6 | `GET /api/v1/stream` or `GET /api/v1/ws` |
| Narratives | 7 | `GET /api/v1/assets/{asset_id}/narratives`, `GET /api/v1/narratives/{narrative_id}` |
| Graph | 7 | `GET /api/v1/campaigns/{campaign_id}/graph`, `GET /api/v1/alerts/{alert_id}/graph` |
| Evidence | 9 | `GET /api/v1/alerts/{alert_id}/evidence` |
| Explain | 9 | `GET /api/v1/alerts/{alert_id}/explanation` |
| Replay | 10 | `POST /api/v1/replays`, `POST /api/v1/replays/{id}/start`, `POST /api/v1/replays/{id}/pause`, `GET /api/v1/replays/{id}` |
| Evaluation | 10 | `GET /api/v1/replays/{id}/metrics`, `GET /api/v1/evaluations/{id}` |
| Investigation | 9 | `POST /api/v1/investigations`, `GET /api/v1/investigations/{id}`, `POST /api/v1/investigations/{id}/feedback` |

## 7. Data Store Distribution By Phase

| Store | First Used | Purpose |
|---|---:|---|
| PostgreSQL | 1 | control plane, campaigns, alerts, investigations, metadata |
| TimescaleDB | 2 | market trades, candles, orderbook features, feature windows |
| Redis | 1 | dedupe, latest state, cache, source freshness, online feature snapshots |
| Redpanda | 1 | durable stream log, replay, consumer groups |
| Local/object Parquet archive | 2 | bronze raw immutable events |
| Qdrant | 7 | social/narrative embeddings and time-bounded disclosure retrieval |
| Neo4j | 7 | coordination/evidence graph projection |
| MLflow | 10 | model versions, artifacts, hashes, candidate/champion aliases |

## 8. Testing Distribution By Phase

| Phase | Required Tests |
|---:|---|
| 1 | schema validation, migration test, health checks, Docker boot |
| 2 | market dedupe, event-time ordering, replay determinism, source health |
| 3 | social dedupe, asset resolver ambiguity, pseudonymization |
| 4 | feature windows, late events, feature revisions, lineage |
| 5 | detector scoring, threshold behavior, missing-model behavior, data-quality confidence |
| 6 | campaign transitions, idempotent alerts, WebSocket/SSE event delivery, concurrency |
| 7 | narrative clustering, graph projection, graph-worker failure isolation |
| 8 | temporal leakage prevention, claim verification correctness, retrieval metadata |
| 9 | immutable evidence, deterministic explanation fallback, analyst feedback linkage |
| 10 | replay isolation, replay metrics, model contract failure, MLflow artifact hash |
| 11 | failure tests, backpressure, circuit breakers, invalid schema handling |
| 12 | full end-to-end scenario regression |

## 9. Definition Of Done Checklist

- [ ] market replay produces canonical events;
- [ ] social replay produces canonical events;
- [ ] duplicate events do not double-count;
- [ ] event-time windows work;
- [ ] late events are handled;
- [ ] feature windows are persisted;
- [ ] online latest features are available;
- [ ] market detector scores assets;
- [ ] social detector scores assets;
- [ ] coordination score is generated;
- [ ] fusion engine creates calibrated risk;
- [ ] campaign state persists across windows;
- [ ] alert state machine works;
- [ ] WebSocket/SSE pushes updates;
- [ ] narrative clustering works;
- [ ] Neo4j evidence graph works;
- [ ] claim retrieval is time-bounded;
- [ ] alert evidence is immutable or revisioned;
- [ ] deterministic explanations work;
- [ ] LLM failure does not break detection;
- [ ] replay is deterministic;
- [ ] one full scenario is covered by integration tests;
- [ ] MLflow records model versions;
- [ ] false-positive hard negatives are evaluated;
- [ ] final system reports detection lead time.

## 10. Deferred Scope

Do not build these until the core detector works:

- Kubernetes;
- multi-region deployment;
- service mesh;
- full enterprise SSO;
- complex organization hierarchy;
- mobile app;
- full feature-store platform;
- Flink/Spark cluster;
- multiple GNN architectures;
- custom LLM fine-tuning;
- marketplace payments;
- buyer/seller workflows;
- listings and checkout;
- marketplace disputes or reviews.

## 11. Highest-Priority First 10 Tasks

1. Define `Asset`, `MarketTrade`, `SocialPost`, `FeatureWindow`, `Campaign`, and `Alert`.
2. Build Docker Compose with FastAPI, Postgres/Timescale, Redis, and Redpanda.
3. Add Alembic migrations and base database tables.
4. Define canonical event envelope and Pydantic schemas.
5. Build `ReplayProvider`.
6. Build market normalizer and dedupe.
7. Build social normalizer and asset resolver.
8. Build 1-minute and 5-minute rolling feature windows.
9. Implement market/social baseline scores.
10. Implement campaign and alert state machines.

## 12. Final Recommendation

Build the backend around the real intelligence pipeline:

```text
market ingestion
social ingestion
event time
deduplication
feature windows
market detector
social detector
coordination detector
graph intelligence
claim verification
fusion
campaign state
alert state
evidence snapshots
analyst investigation
replay evaluation
MLOps
```

This phase distribution satisfies the review's corrected architecture and produces the strongest hackathon outcome: a working, explainable, replayable pump-and-dump surveillance backend instead of a generic marketplace backend.
