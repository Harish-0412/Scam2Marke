import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from sqlalchemy import select

from scam2market.common.logging import get_logger
from scam2market.config.settings import get_settings
from scam2market.db.models import SourceConnectorRunModel, SourcePolicyModel
from scam2market.db.session import AsyncSessionLocal
from scam2market.narratives.embeddings import DeterministicHashEmbedding, InMemoryVectorIndex
from scam2market.verification.connectors import ConnectorError, build_connector
from scam2market.verification.repository import SqlVerificationRepository
from scam2market.verification.service import DisclosureIngestionService

logger = get_logger(__name__)


async def poll_once(client: httpx.AsyncClient | None = None) -> None:
    settings = get_settings()
    owns_client = client is None
    client = client or httpx.AsyncClient()
    ingestion = DisclosureIngestionService(
        repository=SqlVerificationRepository(AsyncSessionLocal),
        embedding=DeterministicHashEmbedding(settings.embedding_dimensions),
        vector_index=InMemoryVectorIndex(),
    )
    try:
        async with AsyncSessionLocal() as session:
            now = datetime.now(tz=UTC)
            policies = (
                await session.scalars(
                    select(SourcePolicyModel).where(
                        SourcePolicyModel.enabled.is_(True),
                        SourcePolicyModel.effective_from <= now,
                        (SourcePolicyModel.effective_to.is_(None))
                        | (SourcePolicyModel.effective_to > now),
                    )
                )
            ).all()
        for policy in policies:
            try:
                await _run_policy(
                    policy, ingestion, client, settings.disclosure_connector_timeout_seconds
                )
            except Exception:
                logger.exception(
                    "disclosure_policy_run_failed",
                    extra={"source_policy_id": str(policy.source_policy_id)},
                )
    finally:
        if owns_client:
            await client.aclose()


async def _run_policy(
    policy: SourcePolicyModel,
    ingestion: DisclosureIngestionService,
    client: httpx.AsyncClient,
    timeout_seconds: float,
) -> None:
    started = datetime.now(tz=UTC)
    run_id = uuid4()
    async with AsyncSessionLocal() as session:
        previous_run = await session.scalar(
            select(SourceConnectorRunModel)
            .where(SourceConnectorRunModel.source_policy_id == policy.source_policy_id)
            .order_by(SourceConnectorRunModel.started_at.desc())
            .limit(1)
        )
        checkpoint = dict(previous_run.checkpoint_json) if previous_run else {}
        session.add(
            SourceConnectorRunModel(
                connector_run_id=run_id,
                source_policy_id=policy.source_policy_id,
                status="RUNNING",
                started_at=started,
                checkpoint_json=checkpoint,
                max_staleness_seconds=int(
                    policy.connector_config_json.get("max_staleness_seconds", 86400)
                ),
                error_json={},
            )
        )
        await session.commit()
    fetched = ingested = unchanged = errors = 0
    watermark = previous_run.source_watermark if previous_run else None
    status = "SUCCESS"
    error_json: dict[str, object] = {}
    try:
        connector = build_connector(
            policy.connector_type,
            policy_id=policy.source_policy_id,
            source_name=policy.name,
            policy_version=policy.policy_version,
            trust_score=policy.trust_score,
            config=policy.connector_config_json,
            canonical_domains=policy.canonical_domains_json,
            logical_source_key=policy.name,
            client=client,
            timeout_seconds=timeout_seconds,
        )
        previous_checkpoint = dict(checkpoint)
        batch = await connector.fetch(previous_checkpoint)
        fetched = len(batch.documents)
        next_checkpoint = batch.checkpoint
        next_watermark = batch.source_watermark
        for document in batch.documents:
            try:
                prepared = document.model_copy(update={"connector_run_id": run_id})
                if await ingestion.ingest(prepared, assign_version=True, preserve_timestamps=False):
                    ingested += 1
                    next_watermark = (
                        max(next_watermark, document.published_at)
                        if next_watermark
                        else document.published_at
                    )
                else:
                    unchanged += 1
            except Exception as exc:
                errors += 1
                error_json = {"type": type(exc).__name__, "message": str(exc)}
        if errors:
            status = "PARTIAL" if ingested else "FAILED"
            checkpoint = previous_checkpoint
            watermark = previous_run.source_watermark if previous_run else None
        else:
            checkpoint = next_checkpoint
            watermark = next_watermark
    except Exception as exc:
        errors = 1
        status = (
            "RATE_LIMITED" if isinstance(exc, ConnectorError) and exc.rate_limited else "FAILED"
        )
        error_json = {"type": type(exc).__name__, "message": str(exc)}
    completed = datetime.now(tz=UTC)
    async with AsyncSessionLocal() as session:
        run = await session.get(SourceConnectorRunModel, run_id)
        assert run is not None
        run.status = status
        run.completed_at = completed
        run.fetched_count = fetched
        run.ingested_count = ingested
        run.unchanged_count = unchanged
        run.error_count = errors
        run.error_json = error_json
        run.source_watermark = watermark
        run.lag_seconds = max(0.0, (completed - watermark).total_seconds()) if watermark else None
        run.checkpoint_json = {
            **checkpoint,
            "completed_at": completed.isoformat(),
            "source_watermark": watermark.isoformat() if watermark else None,
        }
        await session.commit()


async def run() -> None:
    settings = get_settings()
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("disclosure_connector_poll_failed")
        await asyncio.sleep(settings.disclosure_connector_poll_interval_seconds)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
