import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.features.schemas import FeatureSnapshot
from scam2market.narratives.clustering import DeterministicNarrativeClusterer
from scam2market.narratives.embeddings import (
    DeterministicHashEmbedding,
    QdrantVectorIndex,
)
from scam2market.narratives.graph import Neo4jCoordinationGraphProjector
from scam2market.narratives.repository import SqlNarrativeRepository
from scam2market.narratives.service import NarrativeIntelligenceService
from scam2market.schemas.events import EventType
from scam2market.streaming.consumer import EventConsumer

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    embedding = DeterministicHashEmbedding(settings.embedding_dimensions)
    vector_index = QdrantVectorIndex(
        str(settings.qdrant_url), settings.qdrant_post_collection, embedding.dimensions
    )
    projector = Neo4jCoordinationGraphProjector(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
    )
    service = NarrativeIntelligenceService(
        repository=SqlNarrativeRepository(AsyncSessionLocal),
        embedding=embedding,
        vector_index=vector_index,
        graph_projector=projector,
        clusterer=DeterministicNarrativeClusterer(settings.narrative_similarity_threshold),
    )
    try:
        async with EventConsumer(
            ("features.market.v1", "features.social.v1"),
            group_id="narrative-graph-worker-v2",
        ) as consumer:
            async for record in consumer.records():
                if record.event.event_type in {
                    EventType.feature_window_finalized,
                    EventType.feature_window_corrected,
                }:
                    snapshot = FeatureSnapshot.model_validate(record.event.payload)
                    graph = await service.process(snapshot)
                    if graph is None:
                        logger.info(
                            "narrative_window_empty",
                            extra={"feature_window_id": str(snapshot.feature_window_id)},
                        )
                await consumer.commit(record)
    finally:
        await vector_index.close()
        await projector.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
