import asyncio
import logging
from typing import Any

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)
app = FastAPI()


class ThreatIndicator(BaseModel):
    id: str
    type: str
    description: str
    created_at: str


_indicators: list[ThreatIndicator] = []
_feed_task: asyncio.Task[None] | None = None


async def fetch_stix_feed() -> None:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("https://example.com/mock_stix_feed.json")
            response.raise_for_status()
            payload: object = response.json()
            if not isinstance(payload, dict):
                raise ValueError("STIX response must be a JSON object")
            raw_indicators = payload.get("indicators", [])
            if not isinstance(raw_indicators, list):
                raise ValueError("STIX indicators must be a list")
            for raw in raw_indicators:
                if not isinstance(raw, dict):
                    continue
                item: dict[str, Any] = {str(key): value for key, value in raw.items()}
                _indicators.append(
                    ThreatIndicator(
                        id=str(item.get("id", "")),
                        type=str(item.get("type", "unknown")),
                        description=str(item.get("description", "")),
                        created_at=str(item.get("created_at", "")),
                    )
                )
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("stix_feed_fetch_failed", extra={"error": repr(error)})


async def _feed_loop() -> None:
    while True:
        await fetch_stix_feed()
        await asyncio.sleep(60)


@app.on_event("startup")
async def start_feed_loop() -> None:
    global _feed_task
    if _feed_task is None or _feed_task.done():
        _feed_task = asyncio.create_task(_feed_loop())


@app.get("/v1/threat_indicators", response_model=list[ThreatIndicator])
async def list_indicators() -> list[ThreatIndicator]:
    return list(_indicators)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
