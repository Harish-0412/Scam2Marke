# Explainability and Threat Intelligence Implementation

## Scope

Migration `0015_explain_threat` adds deterministic score identity/scope, exact decision traces,
durable model explanations, canonical threat indicators, provider observations, feed health and
checkpoint state, deterministic asset matches, and cutoff-bound threat context snapshots. Prior
migrations and Phase 8 official verification structures are unchanged.

## Explainability

- Fusion emits an exact typed calculation trace at score time; no SHAP, joblib, surrogate model, or
  post-hoc approximation is used.
- Score and event payloads include deterministic `model_score_id` values.
- The worker validates `FusionResult`, inserts `model_explanations` idempotently, and commits the
  consumed Kafka record only after successful persistence.
- Explanation reads are authorized through tenant campaign or replay scope relationships. Platform
  administrators retain cross-tenant operational access.
- Legacy `explainability_outputs` is deprecated and unused. It remains to avoid a destructive
  migration of previously deployed data.

## Threat Intelligence

- `OTXClient` uses subscribed-pulse REST responses, `X-OTX-API-KEY`, disabled redirects, a fixed
  HTTPS host, bounded page/record/response sizes, Retry-After classification, and malformed-item
  isolation.
- Canonical IDs derive from normalized type/value. Provider observation IDs and threat match IDs
  are deterministic, making retries idempotent.
- Feed checkpoint and success status are advanced only after ingestion/matching commits. Error and
  rate-limit updates retain the prior successful checkpoint.
- Matching supports exact URL, domain, IPv4/IPv6, MD5/SHA1/SHA256 candidates and links posts to
  assets through `post_asset_mentions`.
- Context selection enforces post event and local provider-fetch cutoffs. Disabled, unavailable,
  stale, no-match, and matched states remain explicit.
- Matched context is positive-only, configurable/capped, and guarded from independently causing
  HIGH or CRITICAL outcomes. Unavailable/stale expected context reduces confidence.

## Operations

The standalone ports 8001 and 8002 and their FastAPI prototypes were removed. Both durable workers
have package scripts and `unless-stopped` Compose restart policies. Source/readiness health reads the
durable OTX feed row instead of inferring health from credential presence. The OpenAPI contract was
regenerated with all five authenticated routes.

## External Validation

Live OTX credentials, real provider rate-limit behavior, PostgreSQL migration upgrade/downgrade,
Kafka delivery/rebalance behavior, and production tenant data volume require validation in the
deployed integration environment. No external OTX request was made during local tests.
