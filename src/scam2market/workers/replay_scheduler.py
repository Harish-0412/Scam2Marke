import asyncio
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select

from scam2market.common.logging import configure_logging, get_logger
from scam2market.common.time import utc_now
from scam2market.config.settings import get_settings
from scam2market.db.models import AssetModel, ReplaySessionModel
from scam2market.db.session import AsyncSessionLocal
from scam2market.ingestion.market import MarketIngestionService, SyntheticProvider
from scam2market.ingestion.quality import SourceQualityTracker
from scam2market.ingestion.scenarios import load_scenario_manifest
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
    scenario = load_scenario_manifest()
    asset = Asset(
        asset_id=scenario.asset_id,
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
                    metadata_json={
                        "dataset_id": scenario.scenario_id,
                        "scenario_version": scenario.scenario_version,
                        "seed": scenario.seed,
                    },
                )
            )
        session.add(
            ReplaySessionModel(
                replay_session_id=replay_session_id,
                dataset_id=scenario.scenario_id,
                scope_id=str(replay_session_id),
                scenario_version=scenario.scenario_version,
                manifest_hash=hashlib.sha256(
                    json.dumps(
                        scenario.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                random_seed=scenario.seed,
                speed_multiplier=0.0,
                status="RUNNING",
                configuration_json={
                    "isolation": {
                        "scope_id": str(replay_session_id),
                        "publishes_to_live": False,
                    }
                },
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
    scenario = load_scenario_manifest()
    replay_session_id = uuid4()
    asset = await _create_replay_session(replay_session_id)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    market_service = MarketIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(settings.market_freshness_threshold_seconds),
    )
    social_service = SocialIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(settings.social_freshness_threshold_seconds),
        pseudonymizer=AuthorPseudonymizer(
            settings.author_pseudonymization_key,
            key_version=settings.author_pseudonymization_key_version,
        ),
        resolver=AssetMentionResolver(AssetRegistry([asset])),
    )
    await publisher.start()
    try:
        market_count, social_count = await asyncio.gather(
            market_service.run_provider(SyntheticProvider(), str(replay_session_id)),
            social_service.run_provider(SyntheticSocialProvider(), str(replay_session_id)),
        )
        if market_count != scenario.expected_event_counts.market:
            raise RuntimeError(
                f"market replay count {market_count} does not match manifest "
                f"{scenario.expected_event_counts.market}"
            )
        if social_count != scenario.expected_event_counts.social:
            raise RuntimeError(
                f"social replay count {social_count} does not match manifest "
                f"{scenario.expected_event_counts.social}"
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


async def run_queued_session(replay_session_id: UUID) -> None:
    """Execute a replay created through the API control plane."""
    settings = get_settings()
    configure_logging(settings.log_level)
    async with AsyncSessionLocal.begin() as session:
        replay = await session.get(ReplaySessionModel, replay_session_id, with_for_update=True)
        if replay is None or replay.status != "QUEUED":
            return
        scenario = load_scenario_manifest(f"{replay.dataset_id}.yaml")
        asset = Asset(
            asset_id=scenario.asset_id,
            symbol="S2M",
            name="Scam2Market Demo Asset",
            asset_type=AssetType.synthetic,
            quote_asset="USDT",
        )
        if await session.get(AssetModel, asset.asset_id) is None:
            session.add(
                AssetModel(
                    asset_id=asset.asset_id,
                    symbol=asset.symbol,
                    name=asset.name,
                    asset_type=asset.asset_type.value,
                    quote_asset=asset.quote_asset,
                    metadata_json={"dataset_id": scenario.scenario_id},
                )
            )
        replay.status = "RUNNING"
        replay.started_at = utc_now()
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    market_service = MarketIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(settings.market_freshness_threshold_seconds),
    )
    social_service = SocialIngestionService(
        dedupe=state,
        state=state,
        publisher=publisher,
        quality=SourceQualityTracker(settings.social_freshness_threshold_seconds),
        pseudonymizer=AuthorPseudonymizer(
            settings.author_pseudonymization_key,
            key_version=settings.author_pseudonymization_key_version,
        ),
        resolver=AssetMentionResolver(AssetRegistry([asset])),
    )
    await publisher.start()
    try:
        market_count, social_count = await asyncio.gather(
            market_service.run_provider(SyntheticProvider(), str(replay_session_id)),
            social_service.run_provider(SyntheticSocialProvider(), str(replay_session_id)),
        )
        if market_count != scenario.expected_event_counts.market:
            raise RuntimeError("market replay event count mismatch")
        if social_count != scenario.expected_event_counts.social:
            raise RuntimeError("social replay event count mismatch")
    except Exception:
        await _finish_replay_session(replay_session_id, "FAILED")
        raise
    else:
        await _finish_replay_session(replay_session_id, "COMPLETED")
    finally:
        await publisher.stop()
        await state.close()


async def run_control_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        async with AsyncSessionLocal() as session:
            replay_id = await session.scalar(
                select(ReplaySessionModel.replay_session_id)
                .where(ReplaySessionModel.status == "QUEUED")
                .order_by(ReplaySessionModel.created_at)
                .limit(1)
            )
        if replay_id is None:
            await asyncio.sleep(1)
            continue
        try:
            await run_queued_session(replay_id)
        except Exception:
            logger.exception("queued_replay_failed", extra={"replay_session_id": str(replay_id)})


def control_worker_main() -> None:
    asyncio.run(run_control_worker())


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
