import logging
from time import perf_counter
from typing import Any

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

HTTP_REQUESTS = Counter(
    "scam2market_http_requests_total", "HTTP requests", ("method", "path", "status")
)
HTTP_LATENCY = Histogram(
    "scam2market_http_request_duration_seconds", "HTTP request latency", ("method", "path")
)
DEPENDENCY_HEALTH = Gauge(
    "scam2market_dependency_healthy", "Dependency health (1 healthy, 0 degraded)", ("dependency",)
)
RATE_LIMITED = Counter("scam2market_rate_limited_total", "Rejected API requests")
GUARDRAIL_REJECTIONS = Counter(
    "scam2market_guardrail_rejections_total", "Rejected untrusted content", ("reason",)
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(perf_counter() - started)
        return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def configure_tracing(app: FastAPI, *, service_name: str, endpoint: str | None) -> bool:
    """Configure OTLP tracing when OpenTelemetry packages and an endpoint are available."""
    if not endpoint:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("opentelemetry_packages_unavailable")
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    return True


def set_dependency_health(name: str, healthy: bool) -> None:
    DEPENDENCY_HEALTH.labels(name).set(1 if healthy else 0)


def metric_snapshot() -> dict[str, Any]:
    return {"prometheus": True, "endpoint": "/api/v1/metrics"}
