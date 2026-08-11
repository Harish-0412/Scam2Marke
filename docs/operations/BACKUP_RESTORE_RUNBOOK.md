# Backup And Restore Runbook

## Recovery Objectives

- PostgreSQL/TimescaleDB: RPO 15 minutes, RTO 60 minutes for a production deployment.
- Neo4j, Qdrant, and MLflow: rebuildable projections/artifacts; retain daily snapshots when rebuilding
  would exceed the RTO.
- Redpanda: preserve replayable topics according to the event-retention policy.
- Immutable raw Parquet: copy to versioned object storage with retention lock in production.

## Backup

1. Run `pg_dump --format=custom --dbname "$DATABASE_URL" --file scam2market.dump` from a
   network-isolated maintenance runner.
2. Record the Alembic revision with `alembic current` beside the backup.
3. Snapshot Redpanda volumes or use tiered storage; snapshot Neo4j, Qdrant, and MLflow volumes.
4. Encrypt backup artifacts, write a SHA-256 manifest, and store them under a separate credential.
5. Test restoration into an isolated database at least monthly.

## Restore

1. Stop API mutations and workers while leaving health endpoints available in maintenance mode.
2. Provision an empty PostgreSQL database at the recorded compatible major version.
3. Run `pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" scam2market.dump`.
4. Run `alembic upgrade head`, then verify the immutable evidence triggers are present.
5. Restore or rebuild Qdrant/Neo4j projections from retained events and evidence snapshots.
6. Run `python scripts/verify_release.py` and one deterministic replay before reopening traffic.
7. Record the restore, artifact hashes, operator, and validation results in the incident log.

Never place credentials, database dumps, or production evidence exports in Git.
