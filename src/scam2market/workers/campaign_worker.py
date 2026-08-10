import asyncio

from scam2market.campaigns.repository import SqlCampaignRepository
from scam2market.campaigns.service import CampaignService
from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.streaming.consumer import EventConsumer

logger = get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    service = CampaignService(
        SqlCampaignRepository(
            AsyncSessionLocal,
            merge_gap_seconds=settings.campaign_merge_gap_seconds,
            suppression_seconds=settings.alert_suppression_seconds,
            lock_retry_count=settings.campaign_lock_retry_count,
            lock_retry_backoff_ms=settings.campaign_lock_retry_backoff_ms,
        )
    )
    async with EventConsumer(
        ("model.fusion.score.v1",), group_id="campaign-alert-worker-v2"
    ) as consumer:
        async for record in consumer.records():
            try:
                await service.process(record.event)
            except Exception:
                logger.exception("campaign_event_failed", extra={"event_id": record.event.event_id})
                raise
            await consumer.commit(record)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
