# Production Reliability Runbook

## Service Objectives

| Indicator | Objective | Window |
|---|---:|---:|
| Authenticated API availability excluding client errors | 99.9% | rolling 30 days |
| API p95 response latency | under 500 ms | rolling 5 minutes |
| Alert event to notification enqueue p95 | under 30 seconds | rolling 30 days |
| Market/social source freshness | within configured thresholds for 99% of windows | rolling 30 days |
| Logical backup completion | one successful encrypted backup per 24 hours | daily |
| Restore verification | one successful isolated restore | weekly |

Target recovery point is 24 hours for logical backups, supplemented by the managed TimescaleDB
provider's point-in-time recovery. Target recovery time is four hours. Restore drills must use a
dedicated database whose name contains `restore-drill`; the script refuses any other target.

## Availability

1. Check `/api/v1/ready` and identify the failing required dependency.
2. Check deployment availability, HPA saturation, ingress target health, and recent rollouts.
3. Roll back to the previous digest when the error-rate increase aligns with a deployment.
4. Declare an incident when the fast-burn alert remains active for ten minutes.

## Latency

Compare API worker CPU, database pool pressure, Redis latency, and Kafka consumer lag. Scale API pods
only when saturation is local; preserve evidence and feature workers when lag is the primary cause.

## Dependency

Keep the API in degraded read-only behavior when possible. Do not bypass TLS or expose managed data
services publicly during recovery. Escalate to the managed provider and record the provider incident.

## Telemetry

Verify Prometheus target discovery, network policy, and `/api/v1/metrics`. Missing telemetry is not
evidence of health and blocks model promotion and release decisions.

## Backup And Restore

Daily backup jobs create a compressed PostgreSQL custom archive, SHA-256 sidecar, KMS-encrypted S3
objects, and an untested tag. The weekly restore drill validates the checksum, restores into an
isolated database, verifies Alembic state and table presence, then changes the object tag to
`restore-tested=true`. Alert when the latest backup exceeds 26 hours or latest successful restore
exceeds eight days.
