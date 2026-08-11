# Scam2Market Phases 11 And 12 Implementation Report

## Phase 11: Reliability, Security, And Hardening

Implemented:

- Prometheus request, latency, dependency, rate-limit, and guardrail metrics in the main API;
- optional OTLP tracing, an OpenTelemetry Collector pipeline, Prometheus, and a provisioned Grafana
  operations dashboard;
- reusable circuit breaker and bounded micro-batching primitives;
- Redis token-bucket API rate limiting, optional mutation API-key enforcement, non-root container,
  a one-shot raw-volume ownership initializer, strict production override, and secret-handling
  guidance;
- prompt-injection and ingestion data-poisoning guardrails;
- database/Redis readiness probes and explicit optional-component states, including disabled OTX;
- persistent model-drift events and auditable policy proposal approval/rejection;
- failure-oriented tests and backup, restore, degradation, and readiness runbooks.

## Phase 12: Contract, Demo, And Deployment

Implemented:

- frozen `v1-frozen-2026-08-11` OpenAPI contract;
- persistent watchlists and asset membership;
- asset overview, score history, unified timeline, campaign detail, alert detail/acknowledgment,
  narrative detail, and graph evidence APIs;
- replay create/start/pause/status/evaluation contract with a queued replay control worker;
- investigation, feedback, evidence, model governance, and operations APIs in one application;
- generated OpenAPI dashboard contract and release verifier;
- production-shaped Compose override, full Compose replay CI job, and release documentation.

## External Deployment Boundary

The repository provides a reproducible local and production-shaped deployment. A public hosted demo,
managed secret store, cloud object storage, DNS/TLS, and cloud infrastructure remain environment-owned
work because no cloud account, domain, or deployment credentials are committed to this repository.

## Phase 8 Reminder

Phase 8 still needs real official-source disclosure/news connectors, source-policy administration, and
dedicated analyst-facing claim-verification evidence views. The deterministic verification engine itself
is already implemented.
