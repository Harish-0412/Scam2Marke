from scam2market.common.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def run() -> None:
    configure_logging()
    logger.info("verification_worker_ready")
