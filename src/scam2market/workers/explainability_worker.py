import asyncio
import logging
from typing import List

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.db.models import ExplainabilityOutputModel
from scam2market.intelligence.explainability_service import ExplainRequest, ExplainResponse, _generate_explanation

logger = logging.getLogger(__name__)

class PredictionEvent(BaseModel):
    model_version: str
    prediction_id: str
    features: dict

async def process_prediction(event: PredictionEvent) -> None:
    explanation, raw_shap = _generate_explanation(event.features)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            out = ExplainabilityOutputModel(
                claim_id=event.prediction_id,  # using prediction_id as claim placeholder
                model_version=event.model_version,
                explanation=str(explanation),
                relevance_score=None,
                generated_at=None,  # default now
            )
            session.add(out)
        await session.commit()

async def run() -> None:
    logger.info("Starting Explainability Worker")
    # Placeholder: In real system, consume from a message broker.
    # Here we just sleep.
    while True:
        await asyncio.sleep(60)

def main() -> None:
    asyncio.run(run())
