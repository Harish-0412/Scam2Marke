from collections.abc import Awaitable, Callable
from time import time

from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware

from scam2market.config.settings import get_settings
from scam2market.monitoring.telemetry import RATE_LIMITED

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])
local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last = tonumber(bucket[2])
if tokens == nil then tokens = capacity; last = now end
tokens = math.min(capacity, tokens + ((now - last) * refill))
local accepted = 0
if tokens >= 1 then tokens = tokens - 1; accepted = 1 end
redis.call('HSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, ttl)
return {accepted, math.floor(tokens)}
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    _excluded = ("/api/v1/health", "/api/v1/ready", "/api/v1/metrics", "/docs", "/openapi.json")

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if not settings.rate_limit_enabled or request.url.path.startswith(self._excluded):
            return await call_next(request)
        client_id = request.headers.get("x-api-client-id")
        if client_id is None:
            client_id = request.client.host if request.client else "unknown"
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            ttl = max(
                1, int(settings.rate_limit_capacity / settings.rate_limit_refill_per_second * 2)
            )
            result = await redis.eval(
                TOKEN_BUCKET_LUA,
                1,
                f"rate-limit:v1:{client_id}",
                settings.rate_limit_capacity,
                settings.rate_limit_refill_per_second,
                time(),
                ttl,
            )
            accepted, remaining = int(result[0]), int(result[1])
        except RedisError:
            if settings.rate_limit_fail_closed:
                return Response(status_code=503, content="rate limiter unavailable")
            return await call_next(request)
        finally:
            await redis.aclose()
        if not accepted:
            RATE_LIMITED.inc()
            return Response(
                status_code=429,
                content="rate limit exceeded",
                headers={"Retry-After": "1", "X-RateLimit-Remaining": "0"},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = get_settings()
        if request.method in {"GET", "HEAD", "OPTIONS"} or not settings.require_api_key:
            return await call_next(request)
        configured = settings.service_api_key
        supplied = request.headers.get("x-api-key")
        if not configured or supplied != configured:
            return Response(status_code=401, content="valid service API key required")
        return await call_next(request)
