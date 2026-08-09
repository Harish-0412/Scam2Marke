import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.social import (
    AssetMentionResolver,
    AssetRegistry,
    AuthorPseudonymizer,
    SocialIngestionService,
    SyntheticSocialProvider,
)
from scam2market.schemas.domain import Asset, AssetType
from scam2market.state import RedisStateStore
from scam2market.streaming.publisher import EventPublisher

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    demo_asset = Asset(
        asset_id="S2MUSDT",
        symbol="S2M",
        name="Scam2Market Demo Asset",
        asset_type=AssetType.synthetic,
        quote_asset="USDT",
    )
    service = SocialIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(settings.social_freshness_threshold_seconds),
        pseudonymizer=AuthorPseudonymizer(
            settings.author_pseudonymization_key,
            key_version=settings.author_pseudonymization_key_version,
        ),
        resolver=AssetMentionResolver(AssetRegistry([demo_asset])),
    )
    await publisher.start()
    try:
        count = await service.run_provider(SyntheticSocialProvider())
        logger.info("social_ingestion_complete", extra={"accepted_event_count": count})
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
