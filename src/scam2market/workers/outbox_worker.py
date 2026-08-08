import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.ingestion.repositories import SqlOutboxRepository
from scam2market.streaming.outbox import OutboxDispatcher
from scam2market.streaming.publisher import EventPublisher

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    publisher = EventPublisher()
    dispatcher = OutboxDispatcher(
        repository=SqlOutboxRepository(AsyncSessionLocal), publisher=publisher
    )
    await publisher.start()
    try:
        while True:
            published = await dispatcher.dispatch_batch()
            if published:
                logger.info("outbox_batch_published", extra={"published_event_count": published})
            await asyncio.sleep(1)
    finally:
        await publisher.stop()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
