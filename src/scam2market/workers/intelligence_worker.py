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
            ("features.market.v1", "features.social.v1"),
            group_id="baseline-intelligence-worker-v1",
        ) as consumer:
            async for event in consumer.events():
                if event.event_type in {
                    EventType.feature_window_finalized,
                    EventType.feature_window_corrected,
                }:
                    await service.score(FeatureSnapshot.model_validate(event.payload))
                await consumer.commit()
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
