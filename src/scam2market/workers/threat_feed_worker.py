import asyncio
from datetime import UTC, datetime, timedelta

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.intelligence.otx_client import OTXClient, OTXRateLimited
from scam2market.intelligence.repository import IntelligenceRepository

logger = get_logger(__name__)


async def poll_once(client: OTXClient, repository: IntelligenceRepository) -> tuple[int, int]:
    pulses = []
    modified_since = await repository.feed_modified_since()
    async for pulse in client.fetch_pulses(
        modified_since=modified_since,
        page_size=get_settings().otx_page_size,
        max_pages=get_settings().otx_max_pages,
        max_records=get_settings().otx_max_records,
    ):
        pulses.append(pulse)
    now = datetime.now(tz=UTC)
    accepted, watermark = await repository.ingest_pulses(pulses, now)
    matched = await repository.backfill_recent_matches(since=modified_since)
    checkpoint = {"modified_since": watermark.isoformat()} if watermark else {}
    await repository.update_feed_status(
        status="HEALTHY",
        checkpoint=checkpoint,
        fetched=len(pulses),
        accepted=accepted,
        success=True,
    )
    logger.info(
        "threat_feed_poll_completed",
        extra={"fetched": len(pulses), "accepted": accepted, "matched": matched},
    )
    return len(pulses), accepted


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    repository = IntelligenceRepository(AsyncSessionLocal)
    if settings.otx_api_key is None:
        await repository.update_feed_status(status="DISABLED")
        logger.info("threat_feed_disabled", extra={"reason": "OTX_API_KEY_NOT_CONFIGURED"})
        while True:
            await asyncio.sleep(settings.otx_poll_interval_seconds)
    client = OTXClient(
        settings.otx_api_key.get_secret_value(),
        base_url=settings.otx_base_url,
        timeout=settings.otx_timeout_seconds,
        max_response_bytes=settings.otx_max_response_bytes,
    )
    try:
        while True:
            try:
                await poll_once(client, repository)
            except OTXRateLimited as exc:
                delay = exc.retry_after if isinstance(exc.retry_after, float) else 300.0
                until = datetime.now(tz=UTC) + timedelta(seconds=delay)
                await repository.update_feed_status(
                    status="RATE_LIMITED", error=str(exc), rate_limited_until=until
                )
                await asyncio.sleep(delay)
                continue
            except Exception as exc:
                logger.exception("threat_feed_poll_failed")
                await repository.update_feed_status(status="ERROR", error=type(exc).__name__)
            await asyncio.sleep(settings.otx_poll_interval_seconds)
    finally:
        await client.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
