import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from scam2market.db.models import ExplainabilityOutputModel
from scam2market.db.session import AsyncSessionLocal
from scam2market.intelligence.explainability_service import (
    _generate_explanation,
)

logger = logging.getLogger(__name__)


class PredictionEvent(BaseModel):
    model_version: str
    prediction_id: str
    features: dict[str, Any]


async def process_prediction(event: PredictionEvent) -> None:
    explanation, _ = _generate_explanation(event.features)
    try:
        claim_id = UUID(event.prediction_id)
    except ValueError:
        claim_id = uuid5(NAMESPACE_URL, f"prediction:{event.prediction_id}")
    relevance = max((abs(value) for value in explanation.values()), default=0.0)
    async with AsyncSessionLocal() as session, session.begin():
        out = ExplainabilityOutputModel(
            claim_id=claim_id,
            model_version=event.model_version,
            explanation=str(explanation),
            relevance_score=relevance,
            generated_at=datetime.now(tz=UTC),
        )
        session.add(out)


async def run() -> None:
    logger.info("Starting Explainability Worker")
    # Placeholder: In real system, consume from a message broker.
    # Here we just sleep.
    while True:
        await asyncio.sleep(60)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
