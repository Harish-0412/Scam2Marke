# Phase 6-8 Architecture Review Checkpoint

**Status:** Work in progress  
**Review source:** `Scam2Market_Phases_6_8_Architecture_Review.md`  
**Checkpoint date:** 2026-08-10

This branch captures the implementation completed before work was intentionally paused. It is
not a deployable release and must not be merged into `main` until the migration and regression
gates below are finished.

## Implemented At This Checkpoint

- Fusion outputs now separate base model version, policy version, enrichment profile, fusion
  revision, evidence cutoff, input snapshot IDs, and deterministic idempotency identity.
- Campaign state tracks the last applied fusion context and rejects stale or less-complete
  asynchronous enrichment.
- Campaign merge and alert suppression continue to use event time.
- Campaign stages use `POSSIBLE_DISTRIBUTION`, guarded skip transitions, confidence, reason codes,
  evidence IDs, and a versioned rule policy.
- Campaign advisory locking uses bounded transaction-scoped try-lock retries.
- Redis real-time subscriptions detect trimmed cursors and emit `stream.reset_required` with the
  authoritative alert snapshot endpoint.
- Narrative clustering uses deterministic centroid and exemplar coherence gates instead of
  unrestricted union-find single-link clustering.
- Narratives separate stable conceptual IDs from content-addressed revision IDs.
- Graph processing records event-time cutoff, source lineage, component status, threshold censoring,
  and Neo4j uniqueness constraints.
- Qdrant metadata/index contracts include scope, asset, event time, embedding version, source,
  platform, language, ingestion time, and narrative revision.
- Disclosures distinguish publication, first-observed, ingestion, and version/supersession data.
- Claim extraction splits compound narratives into deterministic atomic claims and stores canonical
  structured claim payloads.
- Verification uses first-observed availability for historical support, structured matching,
  versioned source policy, and retrospective-only future support.

## Required Before Merge

- Add Alembic migration `0005` for every new persistence field and narrative revision table.
- Finish repository/runtime compatibility checks for existing Phase 6-8 data.
- Update and add the architecture review regression tests.
- Resolve the currently expected fusion test failures caused by the new version/profile contract.
- Run Ruff, MyPy, the complete pytest suite, migration upgrade/downgrade, and Docker replay checks.
- Update the Phase 6-8 freeze criteria document with verified results.

## Last Verification State

- Ruff passed after the current source edits.
- MyPy passed for all 74 source files.
- Existing pytest suite: 54 passed, 2 expected failures in old fusion assertions.
- Docker and migration verification were not run for this checkpoint.
