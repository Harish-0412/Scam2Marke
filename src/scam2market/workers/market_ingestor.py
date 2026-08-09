import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.ingestion.market import MarketIngestionService, SyntheticProvider
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.state import RedisStateStore
from scam2market.streaming.publisher import EventPublisher

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    service = MarketIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(settings.market_freshness_threshold_seconds),
    )
    await publisher.start()
    try:
        count = await service.run_provider(SyntheticProvider())
        logger.info("market_ingestion_complete", extra={"accepted_event_count": count})
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
