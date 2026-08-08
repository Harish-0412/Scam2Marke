from collections.abc import Awaitable, Callable
from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from scam2market.common.logging import get_logger

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = perf_counter()
        correlation_id = request.headers.get("x-correlation-id", str(uuid4()))
        request_id = request.headers.get("x-request-id", str(uuid4()))
        request.state.correlation_id = correlation_id
        request.state.request_id = request_id

        response = await call_next(request)
        latency_ms = round((perf_counter() - started) * 1000, 2)
        response.headers["x-correlation-id"] = correlation_id
        response.headers["x-request-id"] = request_id

        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "correlation_id": correlation_id,
                "latency_ms": latency_ms,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
        )
        return response
