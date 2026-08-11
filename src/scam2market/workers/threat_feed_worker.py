import asyncio
import logging
import os
from datetime import UTC, datetime

from scam2market.db.models import ThreatIndicatorModel
from scam2market.db.session import AsyncSessionLocal
from scam2market.intelligence.otx_client import JsonObject, OTXClient

logger = logging.getLogger(__name__)


async def fetch_and_store_indicators() -> None:
    client = OTXClient()
    try:
        async for pulse in client.fetch_pulses():
            raw_indicators = pulse.get("objects", [])
            if not isinstance(raw_indicators, list):
                logger.warning("otx_pulse_objects_not_list")
                continue
            async with AsyncSessionLocal() as session, session.begin():
                for raw_indicator in raw_indicators:
                    if not isinstance(raw_indicator, dict):
                        continue
                    indicator: JsonObject = {
                        str(key): value for key, value in raw_indicator.items()
                    }
                    indicator_id = indicator.get("id")
                    if not isinstance(indicator_id, str) or not indicator_id:
                        continue
                    first_seen = _parse_datetime(indicator.get("created"))
                    last_seen = _parse_datetime(indicator.get("modified")) or first_seen
                    if first_seen is None:
                        logger.warning(
                            "otx_indicator_missing_created_at",
                            extra={"indicator_id": indicator_id},
                        )
                        continue
                    await session.merge(
                        ThreatIndicatorModel(
                            indicator_id=indicator_id,
                            indicator_type=str(indicator.get("type", "unknown")),
                            source="OTX",
                            severity=str(indicator.get("severity", "low")),
                            description=str(indicator.get("description", "")),
                            raw_json=indicator,
                            first_seen=first_seen,
                            last_seen=last_seen,
                        )
                    )
    finally:
        await client.close()


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def run() -> None:
    logger.info("Starting Threat Feed Worker")
    if not os.getenv("OTX_API_KEY"):
        logger.warning("threat_feed_disabled", extra={"reason": "OTX_API_KEY_NOT_CONFIGURED"})
        while True:
            await asyncio.sleep(3600)
    while True:
        try:
            await fetch_and_store_indicators()
        except Exception:
            logger.exception("threat_feed_poll_failed")
        await asyncio.sleep(300)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
