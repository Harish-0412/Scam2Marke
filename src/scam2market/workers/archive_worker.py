import asyncio

from scam2market.common.logging import configure_logging
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.ingestion.archive import ParquetRawEventArchive
from scam2market.ingestion.repositories import SqlWorkerCheckpointRepository
from scam2market.schemas.events import EventType
from scam2market.streaming.consumer import EventConsumer

MARKET_EVENT_TYPES = {
    EventType.market_trade_received,
    EventType.market_candle_closed,
    EventType.market_orderbook_updated,
}


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    archive = ParquetRawEventArchive(settings.raw_archive_path)
    checkpoints = SqlWorkerCheckpointRepository(AsyncSessionLocal)
    consumer_group = "telemetry-archive-v1"
    topics = (
        "market.trades.v1",
        "market.candles.v1",
        "market.orderbook.v1",
        "social.posts.raw.v1",
    )
    async with EventConsumer(topics, group_id=consumer_group) as consumer:
        async for record in consumer.records():
            event = record.event
            stream = "market" if event.event_type in MARKET_EVENT_TYPES else "social"
            await archive.write(stream, event)
            await checkpoints.save(
                consumer_group=consumer_group,
                topic=record.topic,
                partition=record.partition,
                last_durable_offset=record.offset,
            )
            await consumer.commit(record)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
