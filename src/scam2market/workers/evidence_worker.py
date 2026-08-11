import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.evidence.repository import EvidenceCaptureRepository
from scam2market.schemas.events import EventType
from scam2market.streaming.consumer import EventConsumer

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    repository = EvidenceCaptureRepository(AsyncSessionLocal)
    async with EventConsumer(
        ("alerts.events.v1",), group_id="evidence-ledger-worker-v1"
    ) as consumer:
        async for event in consumer.events():
            if event.event_type in {
                EventType.alert_created,
                EventType.alert_severity_changed,
                EventType.alert_refreshed,
            }:
                snapshot_id = await repository.capture_alert(event)
                logger.info(
                    "evidence_snapshot_captured",
                    extra={
                        "alert_id": event.payload.get("alert_id"),
                        "snapshot_id": str(snapshot_id),
                    },
                )
            await consumer.commit()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
