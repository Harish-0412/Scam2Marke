import redis
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict

app = FastAPI()

# Simple Redis connection (assumes Redis at localhost:6379). In production configure via env vars.
_redis = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# Lua script for atomic token bucket update
# KEYS[1] - bucket key
# ARGV[1] - capacity
# ARGV[2] - refill_rate (tokens per second)
# ARGV[3] - now (timestamp in seconds)
# Returns remaining tokens after attempt, or -1 if insufficient.
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last = tonumber(bucket[2])
if tokens == nil then tokens = capacity; last = now end

local elapsed = now - last
local new_tokens = tokens + (elapsed * refill)
if new_tokens > capacity then new_tokens = capacity end

if new_tokens < 1 then
  -- not enough tokens
  redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
  return -1
else
  new_tokens = new_tokens - 1
  redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
  return new_tokens
end
"""

_bucket_script = _redis.register_script(TOKEN_BUCKET_LUA)


class RateLimitRequest(BaseModel):
    client_id: str  # could be IP or user identifier
    capacity: int = 100  # max tokens
    refill_rate: float = 1.0  # tokens per second


@app.post("/v1/rate_limit/check")
async def check_rate_limit(req: RateLimitRequest):
    now = int(__import__("time").time())
    result = _bucket_script(
        keys=[f"rate_bucket:{req.client_id}"], args=[req.capacity, req.refill_rate, now]
    )
    if result == -1:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return {"remaining": result}


@app.get("/v1/rate_limit/status/{client_id}")
async def status(client_id: str):
    data = _redis.hgetall(f"rate_bucket:{client_id}")
    return data or {"tokens": "unknown", "last_refill": "unknown"}


@app.get("/health")
async def health():
    return {"status": "ok"}
