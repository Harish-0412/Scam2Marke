import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.features.engine import FeatureWindowEngine, FeatureWindowService
from scam2market.features.schemas import FeatureSignal, SignalKind, SourceDomain
from scam2market.features.signals import market_signal, social_signals
from scam2market.ingestion.market import normalize_market_event
from scam2market.ingestion.repositories import SqlFeatureRepository
from scam2market.schemas.domain import AssetMention, SocialPost
from scam2market.schemas.events import CanonicalEvent, EventType
from scam2market.state import RedisStateStore
from scam2market.streaming.consumer import EventConsumer
from scam2market.streaming.publisher import EventPublisher

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    service = FeatureWindowService(
        engine=FeatureWindowEngine(
            intervals_seconds=tuple(settings.feature_window_intervals_seconds),
            allowed_lateness_seconds=settings.feature_allowed_lateness_seconds,
            source_idle_after_seconds=settings.feature_source_idle_after_seconds,
        ),
        repository=SqlFeatureRepository(AsyncSessionLocal),
        state=state,
        publisher=publisher,
    )
    topics = (
        "market.trades.v1",
        "market.candles.v1",
        "market.orderbook.v1",
        "social.posts.normalized.v1",
        "social.mentions.v1",
    )
    await publisher.start()
    try:
        async with EventConsumer(topics, group_id="feature-window-worker-v1") as consumer:
            async for event in consumer.events():
                if event.event_type in {
                    EventType.market_trade_received,
                    EventType.market_candle_closed,
                    EventType.market_orderbook_updated,
                }:
                    datum = normalize_market_event(event)
                    await service.process(market_signal(event, datum))
                    health = await state.get_json(
                        f"source-health:market:{event.source}:{datum.asset_id}"
                    )
                    if health is not None:
                        await service.process(
                            FeatureSignal(
                                event_id=f"{event.event_id}:quality",
                                scope_id=event.replay.replay_session_id or "LIVE",
                                asset_id=datum.asset_id,
                                event_time=event.event_time,
                                ingested_at=event.ingested_at,
                                kind=SignalKind.data_quality,
                                source_domain=SourceDomain.market,
                                values={
                                    "domain": "market",
                                    "source_gap_count": health.get("sequence_gap_count", 0),
                                    "status": health.get("status"),
                                    "source_active": health.get("source_active", True),
                                    "source_idle": health.get("source_idle", False),
                                    "source_degraded": health.get("source_degraded", False),
                                },
                            )
                        )
                elif event.event_type == EventType.social_post_normalized:
                    post = SocialPost.model_validate(event.payload)
                    await state.set_json(
                        f"join:social:post:{post.post_id}", event.model_dump(mode="json")
                    )
                    await _process_social_pair(post.post_id, service, state)
                elif event.event_type == EventType.social_asset_mention_detected:
                    post_id = str(event.payload["post_id"])
                    await state.set_json(
                        f"join:social:mentions:{post_id}", event.model_dump(mode="json")
                    )
                    await _process_social_pair(post_id, service, state)
                # Offsets remain uncommitted so a restart rebuilds deterministic window state.
    finally:
        await publisher.stop()
        await state.close()


async def _process_social_pair(
    post_id: str,
    service: FeatureWindowService,
    state: RedisStateStore,
) -> None:
    post_data = await state.get_json(f"join:social:post:{post_id}")
    mention_data = await state.get_json(f"join:social:mentions:{post_id}")
    if post_data is None or mention_data is None:
        return
    post_event = CanonicalEvent.model_validate(post_data)
    mention_event = CanonicalEvent.model_validate(mention_data)
    post = SocialPost.model_validate(post_event.payload)
    raw_mentions = mention_event.payload.get("mentions", [])
    if not isinstance(raw_mentions, list):
        raise TypeError("social mention event payload must contain a list")
    mentions = [AssetMention.model_validate(item) for item in raw_mentions]
    signals = social_signals(mention_event, post, mentions)
    for signal in signals:
        await service.process(signal)
    health = await state.get_json(f"source-health:social:{mention_event.source}:{post.platform}")
    if health is not None:
        for asset_id in sorted({signal.asset_id for signal in signals}):
            await service.process(
                FeatureSignal(
                    event_id=f"{mention_event.event_id}:quality:{asset_id}",
                    scope_id=mention_event.replay.replay_session_id or "LIVE",
                    asset_id=asset_id,
                    event_time=mention_event.event_time,
                    ingested_at=mention_event.ingested_at,
                    kind=SignalKind.data_quality,
                    source_domain=SourceDomain.social,
                    values={
                        "domain": "social",
                        "source_gap_count": health.get("sequence_gap_count", 0),
                        "status": health.get("status"),
                        "source_active": health.get("source_active", True),
                        "source_idle": health.get("source_idle", False),
                        "source_degraded": health.get("source_degraded", False),
                    },
                )
            )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
