from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from scam2market.api.router import api_router
from scam2market.common.errors import register_exception_handlers
from scam2market.common.logging import configure_logging, get_logger
from scam2market.common.middleware import CorrelationIdMiddleware
from scam2market.config.settings import get_settings
from scam2market.db.session import engine
from scam2market.monitoring.telemetry import PrometheusMiddleware, configure_tracing
from scam2market.security.rate_limiter import RateLimitMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("application_starting", extra={"environment": settings.environment})
    yield
    await engine.dispose()
    logger.info("application_stopping", extra={"environment": settings.environment})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Event-time-aware pump-and-dump intelligence backend.",
        lifespan=lifespan,
    )

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    configure_tracing(
        app,
        service_name="scam2market-api",
        endpoint=settings.otel_exporter_otlp_endpoint,
    )
    return app


app = create_app()
