import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.ingestion.live_providers import MastodonSocialProvider, RssSocialProvider
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.social import (
    AssetMentionResolver,
    AssetRegistry,
    AuthorPseudonymizer,
    SocialIngestionService,
    SocialProvider,
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
    demo_assets = [
        Asset(
            asset_id="S2MUSDT",
            symbol="S2M",
            name="Scam2Market Demo Asset",
            asset_type=AssetType.synthetic,
            quote_asset="USDT",
        ),
        *[
            Asset(
                asset_id=symbol,
                symbol=symbol.removesuffix("USDT"),
                name=symbol,
                asset_type=AssetType.crypto,
                exchange="binance",
                quote_asset="USDT",
            )
            for symbol in settings.live_market_symbols
        ],
    ]
    service = SocialIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(settings.social_freshness_threshold_seconds),
        pseudonymizer=AuthorPseudonymizer(
            settings.author_pseudonymization_key,
            key_version=settings.author_pseudonymization_key_version,
        ),
        resolver=AssetMentionResolver(AssetRegistry(demo_assets)),
    )
    await publisher.start()
    try:
        provider: SocialProvider
        if settings.social_provider.lower() == "mastodon":
            provider = MastodonSocialProvider(
                base_url=settings.mastodon_base_url,
                access_token=settings.mastodon_access_token,
                poll_interval_seconds=settings.social_poll_interval_seconds,
            )
        elif settings.social_provider.lower() == "rss":
            provider = RssSocialProvider(
                settings.social_rss_urls,
                poll_interval_seconds=settings.social_poll_interval_seconds,
            )
        else:
            provider = SyntheticSocialProvider()
        count = await service.run_provider(provider)
        logger.info("social_ingestion_complete", extra={"accepted_event_count": count})
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
