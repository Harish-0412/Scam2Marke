# Checkpoint 3: Analyst Dashboard And Notifications

## Scope

This checkpoint adds the operational analyst workspace and tenant-scoped outbound alert delivery.

## Analyst Workspace

The FastAPI artifact serves `/dashboard/` with live alert, campaign, readiness, and durable worker
checkpoint views. Analysts can filter by severity, search active alerts, inspect alert state, and
acknowledge an alert. The dashboard uses the same OIDC bearer token and tenant boundary as the API;
development headers are only used when development authentication is enabled.

## Notification Pipeline

Tenant administrators can create Slack, Teams, email, and generic webhook channels and subscribe
them by minimum severity, asset, and alert type. `notification-worker` consumes the transactional
`alerts.events.v1` topic and creates an idempotent delivery for each matching subscription.

The dispatcher claims due work using `FOR UPDATE SKIP LOCKED`, commits the claim before network I/O,
and records every outcome in the delivery ledger. Failures use bounded exponential retry and become
terminal after five attempts. Generic webhook requests include `Idempotency-Key` and an HMAC-SHA256
signature. Channel secrets are excluded from all API responses; production deployments should
provide secrets from the platform secret manager rather than plain Compose environment values.

## Verification

- tenant admin permission and cross-tenant channel filtering;
- duplicate event suppression per channel;
- severity subscription matching;
- deterministic webhook signature and idempotency key;
- delivery state persistence;
- dashboard artifact routing;
- migration upgrade/downgrade and Docker worker health.
