import asyncio

from scam2market.common.logging import configure_logging
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.ingestion.market import normalize_market_event
from scam2market.ingestion.repositories import (
    SqlMarketRepository,
    SqlSocialRepository,
    SqlWorkerCheckpointRepository,
)
from scam2market.schemas.events import CanonicalEvent, EventType
from scam2market.state import OnlineStateStore, RedisStateStore
from scam2market.streaming.consumer import EventConsumer

MARKET_EVENT_TYPES = {
    EventType.market_trade_received,
    EventType.market_candle_closed,
    EventType.market_orderbook_updated,
}


async def _persist_social_pair(
    post_id: str,
    repository: SqlSocialRepository,
    state: OnlineStateStore,
) -> bool:
    normalized_data = await state.get_json(f"persistence:social:post:{post_id}")
    mention_data = await state.get_json(f"persistence:social:mentions:{post_id}")
    if normalized_data is None or mention_data is None:
        return False
    await repository.persist_pair(
        CanonicalEvent.model_validate(normalized_data),
        CanonicalEvent.model_validate(mention_data),
    )
    return True


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    state = RedisStateStore(settings.redis_url)
    market_repository = SqlMarketRepository(AsyncSessionLocal)
    social_repository = SqlSocialRepository(AsyncSessionLocal)
    checkpoints = SqlWorkerCheckpointRepository(AsyncSessionLocal)
    consumer_group = "telemetry-persistence-v1"
    topics = (
        "market.trades.v1",
        "market.candles.v1",
        "market.orderbook.v1",
        "social.posts.raw.v1",
        "social.posts.normalized.v1",
        "social.mentions.v1",
    )
    try:
        async with EventConsumer(topics, group_id=consumer_group) as consumer:
            async for record in consumer.records():
                event = record.event
                durable = True
                if event.event_type in MARKET_EVENT_TYPES:
                    await market_repository.persist(event, normalize_market_event(event))
                elif event.event_type == EventType.social_post_received:
                    await social_repository.persist_raw(event)
                elif event.event_type == EventType.social_post_normalized:
                    post_id = str(event.payload["post_id"])
                    await state.set_json(
                        f"persistence:social:post:{post_id}", event.model_dump(mode="json")
                    )
                    durable = await _persist_social_pair(post_id, social_repository, state)
                elif event.event_type == EventType.social_asset_mention_detected:
                    post_id = str(event.payload["post_id"])
                    await state.set_json(
                        f"persistence:social:mentions:{post_id}", event.model_dump(mode="json")
                    )
                    durable = await _persist_social_pair(post_id, social_repository, state)
                if durable:
                    await checkpoints.save(
                        consumer_group=consumer_group,
                        topic=record.topic,
                        partition=record.partition,
                        last_durable_offset=record.offset,
                    )
                    await consumer.commit(record)
    finally:
        await state.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
