# CI/CD Pipeline

## What Runs

### Continuous Integration

`.github/workflows/ci.yml` runs on every push and pull request. It performs:

1. Ruff formatting and lint checks;
2. strict MyPy checks;
3. Alembic migration upgrade, downgrade, and re-upgrade;
4. the complete Pytest suite against TimescaleDB;
5. Docker and Compose validation;
6. a full intelligence/observability stack boot and deterministic replay regression.

CI prevents code that breaks schemas, migrations, event processing, Docker startup, or the demo
scenario from being accepted unnoticed.

### Continuous Delivery

`.github/workflows/cd.yml` runs for `main`, the active implementation branch, version tags, and manual
dispatches. It:

1. repeats the release quality gate against PostgreSQL/TimescaleDB;
2. validates development and production Compose contracts;
3. builds one backend OCI image and publishes it to
   `ghcr.io/harish-0412/scam2marke-backend`;
4. creates branch, commit-SHA, semantic-version, and `latest` tags where applicable;
5. attaches an SBOM and GitHub build-provenance attestation;
6. creates a seven-day deployment bundle pinned to the image digest;
7. optionally deploys `main` to a self-hosted staging runner.

The image digest, rather than a mutable tag, is the deployment identity. This ensures staging runs
the exact artifact that passed the quality gate.

## Is It Free?

The repository is public. GitHub states that standard GitHub-hosted Actions runners are free for
public repositories. Larger runners are still charged. GitHub Free includes 500 MB of Actions artifact
storage and 10 GB of cache storage; the pipeline keeps deployment bundles for only seven days to limit
storage use.

GitHub also states that public packages are free and that Container Registry image storage and
bandwidth are currently free. GitHub may change the Container Registry policy with advance notice.

Official references:

- [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub Packages billing](https://docs.github.com/en/billing/concepts/product-billing/github-packages)
- [Publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)

The following are not automatically free:

- a cloud server or managed container platform for the running backend;
- managed PostgreSQL, Redis, Kafka/Redpanda, Neo4j, Qdrant, or object storage;
- DNS, paid TLS gateways, SMS, commercial market/social feeds, and LLM usage;
- GitHub larger runners or artifact usage beyond the account allowance.

## Enabling Automatic Staging Deployment

Image delivery works without repository secrets because GitHub's scoped `GITHUB_TOKEN` publishes to
GHCR. Runtime deployment remains disabled until infrastructure is deliberately configured.

1. Register a Linux self-hosted GitHub runner with labels `self-hosted`, `linux`, and
   `scam2market-staging` on a protected staging host.
2. Store the production environment at `/etc/scam2market/scam2market.env`, readable only by the
   runner service account. Never put it in Git.
3. Create a GitHub `staging` environment with required reviewers.
4. Add repository variable `ENABLE_STAGING_DEPLOYMENT=true`.
5. Optionally set `SCAM2MARKET_ENV_FILE` to another protected absolute path.
6. Protect `main` and require the CI workflow before merge.

The next successful `main` build will pull and deploy the attested digest. Keep public-repository
self-hosted runners away from pull-request workflows and untrusted forks.

## Release Commands

Pull a published branch or SHA image:

```bash
docker pull ghcr.io/harish-0412/scam2marke-backend:sha-<short-commit>
```

Run a digest-pinned deployment bundle:

```bash
set -a
. ./image.env
set +a
docker compose --env-file /etc/scam2market/scam2market.env \
  -f docker-compose.yml -f docker-compose.production.yml \
  --profile intelligence --profile observability up -d --no-build
```

## Rollback

Select the last healthy image digest from GHCR or a prior deployment artifact, set
`SCAM2MARKET_IMAGE` to that digest, and run the same deployment command. Database rollback must follow
the migration runbook; never automatically downgrade a production schema during an application
rollback.
