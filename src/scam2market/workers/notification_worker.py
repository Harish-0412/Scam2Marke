import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.notifications.service import NotificationService
from scam2market.streaming.consumer import EventConsumer

logger = get_logger(__name__)


async def _consume(service: NotificationService) -> None:
    async with EventConsumer(
        ("alerts.events.v1",), group_id="notification-delivery-v1"
    ) as consumer:
        async for record in consumer.records():
            tenant_id = str(record.event.payload.get("tenant_id") or "default")
            created = await service.enqueue(record.event, tenant_id=tenant_id)
            await consumer.commit(record)
            logger.info(
                "notification_event_enqueued",
                extra={"event_id": record.event.event_id, "delivery_count": created},
            )


async def _deliver(service: NotificationService, interval_seconds: float) -> None:
    while True:
        delivered = await service.deliver_due()
        await asyncio.sleep(0 if delivered >= 50 else interval_seconds)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    service = NotificationService(AsyncSessionLocal)
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(_consume(service))
        tasks.create_task(_deliver(service, settings.notification_poll_interval_seconds))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
