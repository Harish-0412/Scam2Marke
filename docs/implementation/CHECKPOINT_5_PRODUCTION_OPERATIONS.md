# Checkpoint 5: Infrastructure, Recovery, TLS, And SLOs

## Infrastructure As Code

The AWS Terraform reference creates three-AZ private networking, private-endpoint EKS with encrypted
Kubernetes secrets, managed multi-AZ Redis, TLS-only MSK, KMS, blocked-public-access/versioned backup
storage, ACM certificate validation, and EKS Pod Identity with a narrow backup/runtime policy.

TimescaleDB is intentionally an external managed service secret. AWS RDS PostgreSQL is not presented
as a TimescaleDB replacement because that would remove hypertables and continuous-aggregate behavior.

The Helm chart requires image digests and workload identity, uses three replicas across zones, HPA,
PDB, network policy, read-only filesystems, dropped Linux capabilities, probes, TLS 1.2/1.3 ALB
ingress, and separate backup/restore CronJobs.

## Recovery

Daily custom-format PostgreSQL archives and SHA-256 sidecars are uploaded to KMS-encrypted,
versioned S3 storage. Weekly restore drills validate checksums and schema state in an isolated target.
Restore scripts fail unless explicit authorization is set and the database URL contains
`restore-drill`. The operational target is RPO 24 hours and RTO four hours, supplemented by the
managed database provider's point-in-time recovery.

## TLS And SLOs

Production Compose terminates automatic ACME TLS through Caddy and emits HSTS plus baseline security
headers. Kubernetes uses ACM and the AWS TLS 1.3/1.2 policy. Prometheus recording and alert rules
cover 99.9% availability burn, 500 ms p95 latency, required dependencies, and missing telemetry.
Every alert links to the production runbook.

`scripts/validate_operations.py` is part of CI and fails when critical encryption, private endpoint,
restore safety, immutable image, or SLO controls are removed.
