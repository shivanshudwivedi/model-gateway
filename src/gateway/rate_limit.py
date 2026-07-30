"""Atomic Redis fixed-window rate limiter."""

from __future__ import annotations

import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from redis.asyncio import Redis

LUA = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RedisRateLimiter:
    def __init__(self, redis: Redis, limit: int, window_seconds: int) -> None:
        self.redis = redis
        self.limit = limit
        self.window_seconds = window_seconds

    async def check(self, subject: str) -> RateLimitDecision:
        window = int(time.time()) // self.window_seconds
        key = f"rate-limit:{subject}:{window}"
        result = self.redis.eval(LUA, 1, key, self.window_seconds)
        current, ttl = await cast(Awaitable[list[int]], result)
        used = int(current)
        retry_after = max(int(ttl), 1)
        return RateLimitDecision(
            allowed=used <= self.limit,
            limit=self.limit,
            remaining=max(self.limit - used, 0),
            retry_after=retry_after,
        )
