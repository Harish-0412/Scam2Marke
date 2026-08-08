from fastapi import APIRouter
from pydantic import BaseModel

from scam2market.config.settings import get_settings
from scam2market.streaming.topics import INITIAL_TOPICS

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


class SourceHealthResponse(BaseModel):
    market_data_age_ms: int | None
    social_data_age_s: int | None
    graph_last_updated_s: int | None
    disclosure_index_age_s: int | None
    status: str


class ConfigResponse(BaseModel):
    topics: list[str]
    phase: str
    architecture: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )


@router.get("/config", response_model=ConfigResponse)
async def config() -> ConfigResponse:
    return ConfigResponse(
        topics=INITIAL_TOPICS,
        phase="phase-5-baseline-fusion",
        architecture="python-fastapi-redpanda-timescale-modular-monolith",
    )


@router.get("/source-health", response_model=SourceHealthResponse)
async def source_health() -> SourceHealthResponse:
    return SourceHealthResponse(
        market_data_age_ms=None,
        social_data_age_s=None,
        graph_last_updated_s=None,
        disclosure_index_age_s=None,
        status="not_started",
    )
