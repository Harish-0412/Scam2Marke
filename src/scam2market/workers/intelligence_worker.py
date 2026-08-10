import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.features.schemas import FeatureSnapshot
from scam2market.ingestion.repositories import SqlScoreRepository
from scam2market.intelligence.fusion import DetectionService
from scam2market.schemas.events import EventType
from scam2market.state import RedisStateStore
from scam2market.streaming.consumer import EventConsumer
from scam2market.streaming.publisher import EventPublisher

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    service = DetectionService(
        repository=SqlScoreRepository(AsyncSessionLocal),
        state=state,
        publisher=publisher,
    )
    await publisher.start()
    try:
        async with EventConsumer(
            (
                "features.market.v1",
                "features.social.v1",
                "graph.features.v1",
                "claim.verification.v1",
            ),
            group_id="baseline-intelligence-worker-v3",
        ) as consumer:
            async for event in consumer.events():
                if event.event_type in {
                    EventType.feature_window_finalized,
                    EventType.feature_window_corrected,
                }:
                    await service.score(FeatureSnapshot.model_validate(event.payload))
                elif event.event_type == EventType.graph_features_computed:
                    features = event.payload["features"]
                    if not isinstance(features, dict):
                        raise TypeError("graph features payload must be an object")
                    graph_score = features.get("graph_score")
                    await service.score(
                        FeatureSnapshot.model_validate(event.payload["feature_snapshot"]),
                        graph_score=(float(graph_score) if graph_score is not None else None),
                        graph_snapshot_id=str(event.payload["graph_snapshot_id"]),
                    )
                elif event.event_type == EventType.claim_verification_completed:
                    graph_score = event.payload.get("graph_score")
                    await service.score(
                        FeatureSnapshot.model_validate(event.payload["feature_snapshot"]),
                        claim_risk=float(event.payload["claim_risk"]),
                        legitimate_event_score=float(event.payload["legitimate_event_score"]),
                        graph_score=(float(graph_score) if graph_score is not None else None),
                        graph_snapshot_id=(
                            str(event.payload["graph_snapshot_id"])
                            if event.payload.get("graph_snapshot_id")
                            else None
                        ),
                        verification_snapshot_id=str(event.payload["verification_snapshot_id"]),
                    )
                await consumer.commit()
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
