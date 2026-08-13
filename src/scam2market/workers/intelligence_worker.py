import asyncio
from collections.abc import Mapping

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.features.schemas import FeatureSnapshot
from scam2market.ingestion.repositories import SqlScoreRepository
from scam2market.intelligence.fusion import DetectionService, FusionEngine
from scam2market.intelligence.repository import IntelligenceRepository
from scam2market.schemas.events import EventType
from scam2market.state import RedisStateStore
from scam2market.streaming.consumer import EventConsumer
from scam2market.streaming.publisher import EventPublisher

logger = get_logger(__name__)


def _verification_snapshot_id(payload: Mapping[str, object], event_id: str) -> str:
    snapshot_id = payload.get("verification_snapshot_id")
    if snapshot_id is not None:
        return str(snapshot_id)
    logger.warning(
        "legacy_verification_event_missing_snapshot_id",
        extra={"event_id": event_id},
    )
    return event_id


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    service = DetectionService(
        repository=SqlScoreRepository(AsyncSessionLocal),
        state=state,
        publisher=publisher,
        fusion=FusionEngine(threat_uplift_cap=settings.threat_uplift_cap),
        threat_repository=IntelligenceRepository(AsyncSessionLocal),
        threat_enabled=settings.otx_api_key is not None,
        threat_freshness_seconds=settings.threat_freshness_seconds,
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
                        verification_snapshot_id=_verification_snapshot_id(
                            event.payload, event.event_id
                        ),
                    )
                await consumer.commit()
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
