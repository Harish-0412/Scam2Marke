from fastapi import FastAPI, HTTPException
import httpx
import asyncio
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI()


class ThreatIndicator(BaseModel):
    id: str
    type: str
    description: str
    created_at: str


# In‑memory store for demo – replace with DB table `threat_indicators`
_indicators: List[ThreatIndicator] = []


async def fetch_stix_feed():
    # Stub: fetch from a mock URL; in production integrate with TAXII client
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get("https://example.com/mock_stix_feed.json")
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("indicators", []):
                indicator = ThreatIndicator(
                    id=item.get("id"),
                    type=item.get("type"),
                    description=item.get("description"),
                    created_at=item.get("created_at"),
                )
                _indicators.append(indicator)
        except Exception as e:
            # In production use proper logging
            print(f"Failed to fetch STIX feed: {e}")


@app.on_event("startup")
async def start_feed_loop():
    # Simple periodic task every 60 seconds
    async def loop():
        while True:
            await fetch_stix_feed()
            await asyncio.sleep(60)

    asyncio.create_task(loop())


@app.get("/v1/threat_indicators", response_model=List[ThreatIndicator])
async def list_indicators():
    return _indicators


@app.get("/health")
async def health():
    return {"status": "ok"}
