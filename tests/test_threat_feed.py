import asyncio
import json
from unittest.mock import AsyncMock, patch
import pytest
from scam2market.intelligence.otx_client import OTXClient
from scam2market.workers.threat_feed_worker import fetch_and_store_indicators
from scam2market.db.models import ThreatIndicatorModel
from scam2market.db.session import AsyncSessionLocal


@pytest.fixture
def mock_otx_pulse():
    return {
        "objects": [
            {
                "id": "indicator-1",
                "type": "malware",
                "severity": "high",
                "description": "Test indicator",
                "created": "2024-01-01T00:00:00Z",
                "modified": "2024-01-02T00:00:00Z",
            }
        ]
    }


@pytest.mark.asyncio
async def test_fetch_and_store_indicators(mock_otx_pulse):
    async def mock_fetch_pulses():
        yield mock_otx_pulse

    with (
        patch.object(OTXClient, "fetch_pulses", mock_fetch_pulses),
        patch.object(OTXClient, "close", AsyncMock()),
    ):
        await fetch_and_store_indicators()
    # Verify DB entry
    async with AsyncSessionLocal() as session:
        result = await session.get(ThreatIndicatorModel, "indicator-1")
        assert result is not None
        assert result.indicator_type == "malware"
        assert result.severity == "high"
