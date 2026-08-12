import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.narratives.embeddings import (
    DeterministicHashEmbedding,
    QdrantVectorIndex,
)
from scam2market.schemas.events import EventType
from scam2market.streaming.consumer import EventConsumer
from scam2market.verification.repository import SqlVerificationRepository
from scam2market.verification.service import (
    DisclosureIngestionService,
    NarrativeVerificationService,
    TimeBoundedClaimVerifier,
    disclosure_from_event,
)

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    repository = SqlVerificationRepository(AsyncSessionLocal)
    embedding = DeterministicHashEmbedding(settings.embedding_dimensions)
    index = QdrantVectorIndex(
        str(settings.qdrant_url),
        settings.qdrant_disclosure_collection,
        embedding.dimensions,
    )
    ingestion = DisclosureIngestionService(
        repository=repository, embedding=embedding, vector_index=index
    )
    verification = NarrativeVerificationService(
        repository,
        TimeBoundedClaimVerifier(
            repository,
            lookback_days=settings.verification_pre_alert_lookback_days,
            future_days=settings.verification_post_alert_horizon_days,
        ),
    )
    try:
        async with EventConsumer(
            ("disclosures.documents.v1", "narrative.events.v1"),
            group_id="claim-verification-worker-v2",
        ) as consumer:
            async for record in consumer.records():
                event = record.event
                if event.event_type == EventType.disclosure_received:
                    await ingestion.ingest(disclosure_from_event(event), preserve_timestamps=True)
                elif event.event_type == EventType.narrative_clustered:
                    try:
                        await verification.process(event)
                    except ValueError as error:
                        logger.warning(
                            "narrative_not_verifiable",
                            extra={"event_id": event.event_id, "reason": str(error)},
                        )
                await consumer.commit(record)
    finally:
        await index.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
