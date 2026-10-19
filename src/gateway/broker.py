"""Durable TaskIQ Redis Stream broker."""

from typing import Any

from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from gateway.config import get_settings

settings = get_settings()
result_backend: RedisAsyncResultBackend[Any] = RedisAsyncResultBackend(
    redis_url=settings.redis_url, result_ex_time=86_400
)
broker = RedisStreamBroker(
    url=settings.redis_url,
    queue_name=settings.taskiq_stream,
    consumer_group_name=settings.taskiq_consumer_group,
    # Recover a pending message only after its database claim can expire.
    idle_timeout=(settings.job_lease_seconds + 1) * 1000,
).with_result_backend(result_backend)
