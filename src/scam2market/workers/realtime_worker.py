import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.realtime import RedisRealtimeBroker
from scam2market.streaming.consumer import EventConsumer

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    broker = RedisRealtimeBroker(
        settings.redis_url,
        settings.realtime_stream_key,
        settings.realtime_stream_max_length,
    )
    try:
        async with EventConsumer(("alerts.events.v1",), group_id="realtime-gateway-v1") as consumer:
            async for record in consumer.records():
                await broker.publish(record.event.model_dump(mode="json"))
                await consumer.commit(record)
    finally:
        await broker.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
