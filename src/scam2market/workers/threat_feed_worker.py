import asyncio
import logging
from typing import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.db.models import ThreatIndicatorModel
from scam2market.intelligence.otx_client import OTXClient

logger = logging.getLogger(__name__)

async def fetch_and_store_indicators() -> None:
    settings = get_settings()
    client = OTXClient()
    async for obj in client.fetch_pulses():
        # OTX objects may contain a list of indicators under "objects"
        indicators = obj.get("objects", [])
        async with AsyncSessionLocal() as session:
            async with session.begin():
                for ind in indicators:
                    indicator = ThreatIndicatorModel(
                        indicator_id=ind.get("id"),
                        indicator_type=ind.get("type", "unknown"),
                        source="OTX",
                        severity=ind.get("severity", "low"),
                        description=ind.get("description", ""),
                        raw_json=ind,
                        first_seen=ind.get("created"),
                        last_seen=ind.get("modified", ind.get("created")),
                    )
                    session.add(indicator)
            await session.commit()
    await client.close()

async def run() -> None:
    logger.info("Starting Threat Feed Worker")
    while True:
        try:
            await fetch_and_store_indicators()
        except Exception as exc:
            logger.exception("Error in threat feed worker: %s", exc)
        await asyncio.sleep(300)  # poll every 5 minutes

def main() -> None:
    asyncio.run(run())
