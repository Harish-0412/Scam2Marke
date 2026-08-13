import asyncio

from scam2market.common.logging import configure_logging, get_logger
from scam2market.config.settings import get_settings
from scam2market.db.session import AsyncSessionLocal
from scam2market.intelligence.fusion import FusionResult
from scam2market.intelligence.repository import IntelligenceRepository
from scam2market.streaming.consumer import EventConsumer

logger = get_logger(__name__)


async def run() -> None:
    configure_logging(get_settings().log_level)
    repository = IntelligenceRepository(AsyncSessionLocal)
    async with EventConsumer(
        ("model.fusion.score.v1",), group_id="explainability-worker-v1"
    ) as consumer:
        async for record in consumer.records():
            result = FusionResult.model_validate(record.event.payload)
            await repository.persist_explanation(result)
            await consumer.commit(record)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
