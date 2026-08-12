import asyncio
import hashlib

import orjson

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.features.engine import FeatureWindowEngine, FeatureWindowService
from scam2market.features.schemas import FeatureSignal, SignalKind, SourceDomain
from scam2market.features.signals import market_signal, social_signals
from scam2market.ingestion.market import normalize_market_event
from scam2market.ingestion.repositories import (
    SqlFeatureRepository,
    SqlWorkerCheckpointRepository,
)
from scam2market.schemas.domain import AssetMention, SocialPost
from scam2market.schemas.events import CanonicalEvent, EventType
from scam2market.state import RedisStateStore
from scam2market.streaming.consumer import ConsumedEvent, EventConsumer
from scam2market.streaming.publisher import EventPublisher

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = RedisStateStore(settings.redis_url)
    publisher = EventPublisher()
    engine = FeatureWindowEngine(
        intervals_seconds=tuple(settings.feature_window_intervals_seconds),
        allowed_lateness_seconds=settings.feature_allowed_lateness_seconds,
        source_idle_after_seconds=settings.feature_source_idle_after_seconds,
    )
    checkpoints = SqlWorkerCheckpointRepository(AsyncSessionLocal)
    consumer_group = "feature-window-worker-v1"
    checkpoint = await checkpoints.latest(consumer_group)
    if checkpoint is not None and checkpoint.state_json is not None:
        encoded = orjson.dumps(checkpoint.state_json, option=orjson.OPT_SORT_KEYS)
        checksum = hashlib.sha256(encoded).hexdigest()
        if checkpoint.state_checksum != checksum:
            raise RuntimeError("feature checkpoint checksum mismatch")
        restored = engine.restore_state(checkpoint.state_json)
        logger.info(
            "feature_checkpoint_restored",
            extra={
                "restored_signal_count": restored,
                "checkpoint_offset": checkpoint.last_durable_offset,
            },
        )
    service = FeatureWindowService(
        engine=engine,
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
        async with EventConsumer(topics, group_id=consumer_group) as consumer:
            async for batch in consumer.batches():
                for record in batch:
                    await _process_event(record.event, service, state)
                state_json = engine.export_state()
                encoded = orjson.dumps(state_json, option=orjson.OPT_SORT_KEYS)
                checksum = hashlib.sha256(encoded).hexdigest()
                latest_by_partition: dict[tuple[str, int], ConsumedEvent] = {}
                for record in batch:
                    latest_by_partition[(record.topic, record.partition)] = record
                for record in latest_by_partition.values():
                    await checkpoints.save(
                        consumer_group=consumer_group,
                        topic=record.topic,
                        partition=record.partition,
                        last_durable_offset=record.offset,
                        feature_state_version="feature-engine-state-v1",
                        state_json=state_json,
                        state_checksum=checksum,
                        event_time=record.event.event_time,
                    )
                    await consumer.commit(record)
    finally:
        await publisher.stop()
        await state.close()


async def _process_event(
    event: CanonicalEvent,
    service: FeatureWindowService,
    state: RedisStateStore,
) -> None:
    if event.event_type in {
        EventType.market_trade_received,
        EventType.market_candle_closed,
        EventType.market_orderbook_updated,
    }:
        datum = normalize_market_event(event)
        await service.process(market_signal(event, datum))
        health = await state.get_json(f"source-health:market:{event.source}:{datum.asset_id}")
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
        await state.set_json(f"join:social:post:{post.post_id}", event.model_dump(mode="json"))
        await _process_social_pair(post.post_id, service, state)
    elif event.event_type == EventType.social_asset_mention_detected:
        post_id = str(event.payload["post_id"])
        await state.set_json(f"join:social:mentions:{post_id}", event.model_dump(mode="json"))
        await _process_social_pair(post_id, service, state)


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
