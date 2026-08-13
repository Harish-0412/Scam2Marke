import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from scam2market.config.settings import get_settings
from scam2market.db.models import EventIngestionLogModel, ThreatFeedStatusModel
from scam2market.db.session import engine, get_db_session
from scam2market.monitoring.telemetry import (
    metric_snapshot,
    metrics_response,
    set_dependency_health,
)
from scam2market.streaming.topics import INITIAL_TOPICS

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    version: str


class DependencyStatus(BaseModel):
    status: str
    required: bool
    latency_ms: float | None = None
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: str
    dependencies: dict[str, DependencyStatus]
    telemetry: dict[str, Any]


class SourceHealthResponse(BaseModel):
    market_data_age_ms: int | None
    social_data_age_s: int | None
    graph_last_updated_s: int | None
    disclosure_index_age_s: int | None
    threat_feed_status: str
    status: str


class ConfigResponse(BaseModel):
    topics: list[str]
    phase: str
    architecture: str
    api_contract: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
        version="1.0.0",
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    settings = get_settings()
    probes = await asyncio.gather(_probe_database(), _probe_redis(), return_exceptions=False)
    dependencies = {probe[0]: probe[1] for probe in probes}
    dependencies.update(
        {
            "neo4j": DependencyStatus(status="optional", required=False),
            "qdrant": DependencyStatus(status="optional", required=False),
            "mlflow": DependencyStatus(status="optional", required=False),
            "otx": await _threat_feed_health(),
        }
    )
    unavailable = [
        name for name, item in dependencies.items() if item.required and item.status != "ok"
    ]
    readiness_status = "unavailable" if unavailable else "ready"
    if unavailable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status=readiness_status,
        dependencies=dependencies,
        telemetry={
            **metric_snapshot(),
            "tracing": bool(settings.otel_exporter_otlp_endpoint),
        },
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return metrics_response()


@router.get("/config", response_model=ConfigResponse)
async def config() -> ConfigResponse:
    return ConfigResponse(
        topics=INITIAL_TOPICS,
        phase="phase-12-contract-and-release",
        architecture="python-fastapi-redpanda-timescale-modular-monolith",
        api_contract="v1-frozen-2026-08-11",
    )


@router.get("/source-health", response_model=SourceHealthResponse)
async def source_health(
    session: AsyncSession = Depends(get_db_session),
) -> SourceHealthResponse:
    market_at = await session.scalar(
        select(func.max(EventIngestionLogModel.event_time)).where(
            EventIngestionLogModel.event_type.like("market.%")
        )
    )
    social_at = await session.scalar(
        select(func.max(EventIngestionLogModel.event_time)).where(
            EventIngestionLogModel.event_type.like("social.%")
        )
    )
    now = datetime.now(tz=UTC)
    market_age_ms = int((now - market_at).total_seconds() * 1000) if market_at else None
    social_age_s = int((now - social_at).total_seconds()) if social_at else None
    status_value = "ok" if market_at and social_at else "not_started"
    threat_status = await session.get(ThreatFeedStatusModel, "OTX")
    return SourceHealthResponse(
        market_data_age_ms=market_age_ms,
        social_data_age_s=social_age_s,
        graph_last_updated_s=None,
        disclosure_index_age_s=None,
        threat_feed_status=threat_status.status.lower() if threat_status else "not_started",
        status=status_value,
    )


async def _probe_database() -> tuple[str, DependencyStatus]:
    started = asyncio.get_running_loop().time()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        set_dependency_health("postgres", False)
        return "postgres", DependencyStatus(
            status="unavailable", required=True, detail=type(exc).__name__
        )
    latency = round((asyncio.get_running_loop().time() - started) * 1000, 2)
    set_dependency_health("postgres", True)
    return "postgres", DependencyStatus(status="ok", required=True, latency_ms=latency)


async def _probe_redis() -> tuple[str, DependencyStatus]:
    settings = get_settings()
    started = asyncio.get_running_loop().time()
    redis = Redis.from_url(settings.redis_url)
    try:
        await asyncio.wait_for(redis.ping(), timeout=settings.dependency_probe_timeout_seconds)
    except Exception as exc:
        set_dependency_health("redis", False)
        return "redis", DependencyStatus(
            status="unavailable", required=True, detail=type(exc).__name__
        )
    finally:
        await redis.aclose()
    latency = round((asyncio.get_running_loop().time() - started) * 1000, 2)
    set_dependency_health("redis", True)
    return "redis", DependencyStatus(status="ok", required=True, latency_ms=latency)


async def _threat_feed_health() -> DependencyStatus:
    async with engine.connect() as connection:
        value = await connection.scalar(
            select(ThreatFeedStatusModel.status).where(ThreatFeedStatusModel.provider == "OTX")
        )
    return DependencyStatus(status=str(value or "not_started").lower(), required=False)
