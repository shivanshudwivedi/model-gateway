import pytest

from gateway.rate_limit import RedisRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.count = 0

    async def eval(self, script: str, keys: int, key: str, window: int) -> list[int]:
        del script, keys, key
        self.count += 1
        return [self.count, window]


@pytest.mark.asyncio
async def test_rate_limit_decisions() -> None:
    redis = FakeRedis()
    limiter = RedisRateLimiter(redis, limit=2, window_seconds=60)  # type: ignore[arg-type]
    first = await limiter.check("tenant")
    second = await limiter.check("tenant")
    third = await limiter.check("tenant")
    assert first.allowed and first.remaining == 1
    assert second.allowed and second.remaining == 0
    assert not third.allowed and third.retry_after == 60
