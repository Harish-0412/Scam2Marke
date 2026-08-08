import asyncio
from uuid import UUID, uuid4

from scam2market.common.logging import configure_logging, get_logger
from scam2market.common.time import utc_now
from scam2market.config.settings import get_settings
from scam2market.db.models import AssetModel, ReplaySessionModel
from scam2market.db.session import AsyncSessionLocal
from scam2market.ingestion.archive import ParquetRawEventArchive
from scam2market.ingestion.market import MarketIngestionService, SyntheticProvider
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.repositories import SqlMarketRepository, SqlSocialRepository
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


async def _create_replay_session(replay_session_id: UUID) -> Asset:
    asset = Asset(
        asset_id="S2MUSDT",
        symbol="S2M",
        name="Scam2Market Demo Asset",
        asset_type=AssetType.synthetic,
        quote_asset="USDT",
    )
    async with AsyncSessionLocal.begin() as session:
        if await session.get(AssetModel, asset.asset_id) is None:
            session.add(
                AssetModel(
                    asset_id=asset.asset_id,
                    symbol=asset.symbol,
                    name=asset.name,
                    asset_type=asset.asset_type.value,
                    quote_asset=asset.quote_asset,
                    metadata_json={"dataset_id": "synthetic-pump-v1"},
                )
            )
        session.add(
            ReplaySessionModel(
                replay_session_id=replay_session_id,
                dataset_id="synthetic-pump-v1",
                speed_multiplier=0.0,
                status="RUNNING",
                started_at=utc_now(),
            )
        )
    return asset


async def _finish_replay_session(replay_session_id: UUID, status: str) -> None:
    async with AsyncSessionLocal.begin() as session:
        replay = await session.get(ReplaySessionModel, replay_session_id)
        if replay is None:
            raise RuntimeError(f"replay session {replay_session_id} disappeared")
        replay.status = status
        replay.completed_at = utc_now()


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    replay_session_id = uuid4()
    asset = await _create_replay_session(replay_session_id)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    archive = ParquetRawEventArchive(settings.raw_archive_path)
    market_service = MarketIngestionService(
        repository=SqlMarketRepository(AsyncSessionLocal),
        dedupe=state,
        state=state,
        archive=archive,
        publisher=publisher,
        quality=SourceQualityTracker(settings.market_freshness_threshold_seconds),
    )
    social_service = SocialIngestionService(
        repository=SqlSocialRepository(AsyncSessionLocal),
        dedupe=state,
        state=state,
        archive=archive,
        publisher=publisher,
        quality=SourceQualityTracker(settings.social_freshness_threshold_seconds),
        pseudonymizer=AuthorPseudonymizer(settings.author_pseudonymization_key),
        resolver=AssetMentionResolver(AssetRegistry([asset])),
    )
    await publisher.start()
    try:
        market_count, social_count = await asyncio.gather(
            market_service.run_provider(SyntheticProvider(), str(replay_session_id)),
            social_service.run_provider(SyntheticSocialProvider(), str(replay_session_id)),
        )
    except Exception:
        await _finish_replay_session(replay_session_id, "FAILED")
        raise
    else:
        await _finish_replay_session(replay_session_id, "COMPLETED")
        logger.info(
            "replay_session_complete",
            extra={
                "replay_session_id": str(replay_session_id),
                "market_event_count": market_count,
                "social_event_count": social_count,
            },
        )
    finally:
        await publisher.stop()
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
