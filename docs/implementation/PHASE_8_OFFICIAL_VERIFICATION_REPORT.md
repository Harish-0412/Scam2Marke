# Phase 8 Official Verification Implementation Report

Status: implemented in the backend on 2026-08-12; environment onboarding and production validation remain open.

## Delivered

- Configurable source policies cover official exchange, project, status, governance, and news RSS/Atom feeds without hardcoded commercial APIs.
- Injectable `httpx` connectors support RSS/Atom, GitHub releases, and SEC EDGAR recent submissions and filing bodies with bounded timeouts, explicit errors, stable source keys, content-version IDs, and the SEC-required configured User-Agent.
- PostgreSQL persistence now includes source trust and license policy, connector runs and checkpoints, disclosure version lineage and availability, and relational supporting, conflicting, contextual, or retrospective evidence snapshots.
- The disclosure connector worker polls enabled policies conditionally with durable checkpoints, records run health and lag, and atomically versions changed content under a logical-source advisory lock. Connector availability is assigned in the persistence transaction; replay ingestion preserves explicit event timestamps.
- Verification uses `available_at <= alert_time`. Documents published earlier but observed or ingested later cannot reduce claim risk. Future amendments remain retrospective.
- Failed, partial, stale, rate-limited, or never-run expected sources degrade absent support to `UNKNOWN` with coverage metadata rather than `UNSUPPORTED`.
- Protected analyst and administration APIs expose claims, verification evidence, disclosures and versions, source policies and runs, and a combined verification timeline. Licensed body display is redacted unless policy explicitly permits it.
- Source-policy creation and replacement are restricted to platform administrators and recorded in the audit ledger. PATCH requires a caller-supplied new `policy_version`, expires the prior row, and inserts an immutable replacement row.

## Operational Ownership

No source registrations are seeded by this change. Operators must create policies with official feed URLs, GitHub repositories, SEC CIKs and compliant contact User-Agents. Credentials, feed registrations, licensed provider agreements, retention decisions, attribution text, network allowlists, monitoring thresholds, and real-world source validation remain environment-owned.

This phase does not claim bundled coverage for every regulator, exchange, project, or licensed provider. SEC EDGAR is the included regulator connector; other official sources can use RSS/Atom where available or require future connector implementations.

## Validation

Focused tests cover connector parsing, conditional checkpoints, source caps, canonical-domain rejection, stable version identity, temporal cutoff equality, persistence-time ingestion, deterministic replay timestamps, amendment authority, asset-scoped outage degradation, mixed supporting/conflicting evidence, and OpenAPI paths. Ruff and focused pytest results are recorded in the implementation handoff.
