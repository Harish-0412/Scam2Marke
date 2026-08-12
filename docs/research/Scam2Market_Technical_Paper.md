# Scam2Market Technical Paper

**Title:** Scam2Market: An Event-Time Multi-Modal Intelligence Backend For Pump-And-Dump Campaign Detection

**Version:** 1.0

**Date:** 2026-08-12

**Repository:** https://github.com/Harish-0412/Scam2Marke

**Current implementation note:** Phase 8 includes configurable RSS/Atom, GitHub Releases, and SEC EDGAR recent-submission connectors, analyst APIs, and availability-safe evidence versioning. Source credentials and registrations, licensed-provider agreements, and operational validation are deployment responsibilities; universal regulator/provider coverage is not claimed.

## Abstract

Scam2Market is a backend intelligence system for detecting suspected pump-and-dump and coordinated promotion campaigns by correlating market microstructure signals, social amplification signals, semantic narrative clusters, graph coordination patterns, disclosure verification, and analyst feedback. The project intentionally avoids marketplace, payment, listing, or dispute-management scope. Its central objective is to produce explainable, replayable, evidence-backed surveillance outputs that can be consumed by an analyst dashboard or downstream notification system.

The novelty of the project lies in combining deterministic event-time replay, multi-modal feature windows, graph/narrative enrichment, temporal claim verification, immutable evidence snapshots, analyst feedback, model governance, and production-shaped deployment controls in one coherent backend architecture. Instead of returning isolated rule-based warnings, the backend maintains campaign state, alert histories, evidence manifests, verification outcomes, and governed model lifecycle metadata.

## 1. Introduction

Pump-and-dump manipulation is difficult to detect because meaningful signals are distributed across multiple domains. Market activity may show abnormal returns, volume, spread movement, order-book imbalance, and buy/sell pressure. Social media may show sudden mention velocity, concentrated authorship, repeated URLs, repost chains, or coordinated hashtags. Official disclosures and reliable news can distinguish legitimate catalysts from unsupported promotional narratives. Analysts then need durable evidence, not just a risk score.

Scam2Market addresses this by implementing an event-time surveillance backend that can ingest market and social data, build reproducible features, score risk, stabilize detections into campaigns, alert analysts, preserve immutable evidence, and evaluate behavior through deterministic replay.

## 2. Problem Statement

The system is designed to answer four operational questions:

1. Is an asset experiencing abnormal market behavior relative to recent baseline?
2. Is social attention rising organically or through concentrated/coordinated amplification?
3. Are the narratives being promoted supported by official disclosures before the alert time?
4. Can the system explain, replay, audit, and improve the alert decision?

A production-ready answer requires more than a classifier. It requires source quality tracking, replayability, tenant isolation, evidence lineage, real-time delivery, and governance over model promotion.

## 3. Research Motivation And Novelty

The project is novel at the implementation level because it treats manipulation detection as an intelligence workflow rather than a one-step prediction problem.

Key novel aspects:

- Event-time-first design: windows, scores, claim retrieval, and replay are based on event time rather than ingestion time.
- Multi-modal correlation: market, social, graph, temporal, and verification signals are represented separately before fusion.
- Campaign state instead of noisy one-off alerts: repeated scores update a campaign lifecycle from early social seeding through pump/dump/post-event stages.
- Temporal claim verification: official-source evidence must exist before the alert time to reduce risk; future documents cannot justify past alerts.
- Evidence preservation: high-risk alerts are linked to immutable evidence snapshots with content hashes and access auditing.
- Governance loop: labels, calibration, drift reports, false-positive feedback, MLflow metadata, and shadow scoring are designed into the backend.
- Production-shaped architecture: CI/CD, Docker, Terraform, Helm, TLS, backups, restore drills, SLOs, and runbooks are included alongside application logic.

## 4. Scope

In scope:

- pump-and-dump intelligence backend;
- market/social ingestion and replay;
- event-time feature windows;
- campaign and alert engine;
- narrative and graph intelligence;
- disclosure and claim verification;
- evidence, investigation, feedback, and evaluation workflows;
- authentication, RBAC, tenancy, observability, and deployment assets.

Out of scope:

- trading execution;
- financial advice;
- marketplace listings;
- payments;
- buyer/seller disputes;
- custody, brokerage, or exchange functionality.

## 5. System Architecture

The backend follows a modular-monolith codebase with worker entrypoints and event-streamed boundaries. This design keeps development and deployment manageable while retaining clear ownership between ingestion, features, scoring, campaign handling, evidence, governance, and operations.

Primary runtime components:

- FastAPI API service;
- market ingestor;
- social ingestor;
- feature worker;
- intelligence worker;
- campaign worker;
- realtime worker;
- narrative/graph worker;
- verification worker;
- evidence worker;
- notification worker;
- replay scheduler;
- archive worker.

Primary storage and infrastructure:

- TimescaleDB/PostgreSQL for relational and time-series state;
- Redis for low-latency state, deduplication, rate limiting, streams, and checkpoints;
- Redpanda/Kafka for event topics;
- Qdrant for embeddings and retrieval;
- Neo4j for graph projection;
- MLflow for experiment and model metadata;
- object storage or local Parquet archive for immutable raw event storage;
- Prometheus, Grafana, and OpenTelemetry for observability.

## 6. Data Model

Core domain objects include `Asset`, `MarketTrade`, `MarketCandle`, `OrderBookUpdate`, `SocialPost`, `AssetMention`, `Disclosure`, `FeatureWindow`, `Narrative`, `GraphSnapshot`, `ModelScore`, `Campaign`, `Alert`, `EvidenceSnapshot`, `Investigation`, and `ReplaySession`.

The canonical event envelope includes event identity, schema version, source metadata, asset partitioning, event time, ingestion time, processing time, replay metadata, trace metadata, and typed payload. This makes replay, lineage, deduplication, and worker recovery auditable.

## 7. Ingestion And Replay Flow

Market ingestion normalizes trades, candles, and order-book snapshots. Social ingestion normalizes posts, pseudonymizes authors, extracts hashtags/cashtags/URLs/mentions, resolves asset mentions, and stores confidence plus resolver version.

Replay exists because manipulation detection must be testable. Deterministic replay allows the same scenario to regenerate the same feature windows, scores, campaigns, alerts, and evidence outputs. Replay sessions are tenant/scope-isolated so demo data does not contaminate production views.

## 8. Feature Engineering

The feature system builds rolling 1-minute and 5-minute windows using event time. Late events can revise provisional windows while finalized windows remain reproducible through lineage and revision records.

Market feature groups include:

- price return;
- volume and relative volume;
- volatility;
- spread;
- top-N depth;
- order-book imbalance;
- trade count;
- buy/sell pressure where available;
- market freshness and quality state.

Social feature groups include:

- mention count;
- unique author count;
- author concentration;
- repost/reply ratio;
- hashtag velocity;
- URL concentration;
- new-author ratio;
- social freshness and quality state.

Additional feature groups include temporal lead/lag signals, baseline confidence, market regime, liquidity class, optional graph features, and claim-verification evidence.

## 9. Detection, Fusion, Campaigns, And Alerts

The scoring layer includes market anomaly, social surge, temporal lead/lag, coordination, claim-risk, legitimate-event, and graph enrichment signals. Fusion keeps missing outputs explicit and lowers confidence when data is degraded.

The campaign engine converts repeated scores into durable campaign state. It supports valid stage transitions, merge windows, alert suppression, severity histories, concurrency control, and idempotent alert creation. This avoids overwhelming analysts with one-off alerts and gives each risk event a lifecycle.

Campaign stages include `NORMAL`, `EARLY_SOCIAL_SEEDING`, `COORDINATED_AMPLIFICATION`, `MARKET_PUMP`, `DISTRIBUTION`, `DUMP`, and `POST_EVENT`.

Alert types include social hype surge, coordinated promotion, unverified narrative, market volume anomaly, market price anomaly, market microstructure anomaly, cross-domain manipulation risk, and possible dump phase.

## 10. Narrative, Graph, And Claim Verification

The narrative pipeline generates deterministic embeddings for replay-stable clustering and can index post/narrative vectors in Qdrant. Graph projection links actors, posts, assets, narratives, campaigns, alerts, and evidence in Neo4j. Cheap graph analytics produce features such as community concentration, synchronized posting, amplifier overlap, propagation depth, and cross-community spread.

The verification engine ingests governed RSS/Atom, GitHub Releases, and SEC EDGAR documents, chunks and indexes them, extracts narrative claims, and verifies whether supporting evidence existed before the alert time. Supported-before-alert evidence can reduce manipulation confidence, while unsupported or conflicting claims increase claim risk. Source policies preserve trust, license, availability, connector-run, and version metadata, and analyst APIs expose supporting, conflicting, and retrospective evidence.

## 11. Evidence, Investigations, And Governance

Scam2Market stores evidence snapshots with hashes, completeness scores, and access-audit controls. Alerts can be linked to deterministic explanations and analyst investigations. Feedback and false-positive reports feed future calibration and policy changes.

Model governance includes calibration labels, calibration metrics, promotion decisions, alias management, drift reports, false-positive budgets, and shadow scoring. Shadow scores are constrained so they cannot control production alerts until explicitly promoted.

## 12. Security And Multi-Tenancy

Security capabilities include OIDC/JWT authentication, development-auth isolation, RBAC, tenant-scoped data, PostgreSQL row-level security, service-account key rotation, rate limiting, non-root containers, production read-only filesystem behavior, prompt-injection/data-poisoning guardrails, and audited sensitive access.

The frontend should use OIDC/JWT in production and should never depend on development auth headers outside local development.

## 13. Deployment And Operations

Local deployment uses Docker Compose. Production-shaped deployment uses a Compose override with Caddy TLS and private data-service ports. The repository also includes Terraform AWS and Helm references for private networking, EKS, Redis, MSK, KMS, ACM, S3 backups, workload identity, digest-pinned deployments, probes, network policy, backup jobs, and restore drills.

The recommended hosted architecture is to deploy the frontend on Vercel or another static/frontend platform, and deploy the backend and workers on a container platform such as Render, Railway, Fly.io, AWS ECS/EKS, Azure Container Apps, or Google Cloud Run. Managed Redis, Kafka/Redpanda, TimescaleDB/PostgreSQL, Qdrant, Neo4j, MLflow, and object storage should be configured separately.

## 14. CI/CD And Quality Controls

CI runs formatting, linting, strict type checking, Alembic migrations, full tests, Docker build, Compose validation, Terraform validation, Helm linting, operations image build, and a deterministic Compose replay regression.

CD publishes a digest-addressed backend image to GitHub Container Registry, attaches SBOM/provenance data, and creates a deployment bundle. Staging deployment is opt-in through a protected self-hosted runner.

## 15. Evaluation Strategy

Evaluation is built around deterministic replay, hard-negative scenarios, detector ablations, calibration labels, false-positive reports, and drift reports. The system should be evaluated not only by classification metrics but also by lead time, evidence completeness, analyst workload, source freshness, and stability under missing/degraded dependencies.

## 16. Limitations

Current limitations:

- source registrations, credentials, licensed-provider agreements, and connectors for regulators without compatible feeds remain environment-owned;
- live provider scaffolding requires production credentials, rate-limit policy, and long-duration validation;
- model accuracy depends on labeled data that must be collected and governed;
- public cloud deployment needs external credentials, DNS, secrets, and provider accounts;
- optional intelligence components can strengthen confidence but must degrade safely when unavailable.

## 17. Conclusion

Scam2Market demonstrates a professional backend architecture for manipulation surveillance: event-time ingestion, replayable features, multi-domain scoring, campaign state, real-time alerts, governed official-source verification, evidence snapshots, analyst workflow, and deployment governance. Its most important next step is onboarding approved production sources, validating them under sustained operation, and pairing the backend with a frontend that consumes the frozen API contract without mock data.

## References

1. FastAPI documentation, https://fastapi.tiangolo.com/
2. Pydantic documentation, https://docs.pydantic.dev/
3. SQLAlchemy documentation, https://docs.sqlalchemy.org/
4. Alembic documentation, https://alembic.sqlalchemy.org/
5. PostgreSQL documentation, https://www.postgresql.org/docs/
6. Timescale documentation, https://docs.timescale.com/
7. Redis documentation, https://redis.io/docs/latest/
8. Redpanda documentation, https://docs.redpanda.com/
9. Redpanda Cloud overview and trial information, https://docs.redpanda.com/cloud-data-platform/get-started/cloud-overview/
10. Qdrant documentation, https://qdrant.tech/documentation/
11. Neo4j documentation, https://neo4j.com/docs/
12. MLflow tracking server documentation, https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/
13. OpenTelemetry documentation, https://opentelemetry.io/docs/
14. Prometheus documentation, https://prometheus.io/docs/
15. Grafana documentation, https://grafana.com/docs/
16. GitHub Actions billing documentation, https://docs.github.com/en/billing/concepts/product-billing/github-actions
17. Vercel Hobby plan documentation, https://vercel.com/docs/plans/hobby
18. Vercel platform limits, https://vercel.com/docs/limits
19. Neon pricing documentation, https://neon.com/pricing
20. Upstash Redis FAQ, https://upstash.com/docs/redis/help/faq
21. OWASP API Security Top 10, https://owasp.org/API-Security/
22. NIST Cybersecurity Framework, https://www.nist.gov/cyberframework
