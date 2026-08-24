import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.ingestion.live_providers import BinanceMarketProvider
from scam2market.ingestion.market import MarketIngestionService, SyntheticProvider
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.resilience.circuit_breaker import CircuitBreaker
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
        provider = (
            BinanceMarketProvider(
                settings.live_market_symbols,
                base_url=settings.binance_base_url,
                poll_interval_seconds=settings.market_poll_interval_seconds,
                circuit_breaker=CircuitBreaker(
                    "binance-market-provider",
                    failure_threshold=settings.circuit_failure_threshold,
                    recovery_seconds=settings.circuit_recovery_seconds,
                ),
            )
            if settings.market_provider.lower() == "binance"
            else SyntheticProvider()
        )
        count = await service.run_provider(provider)
        logger.info("market_ingestion_complete", extra={"accepted_event_count": count})
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
