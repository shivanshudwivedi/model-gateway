"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_client import make_asgi_app
from redis.asyncio import Redis

from gateway import __version__
from gateway.api import router
from gateway.config import get_settings
from gateway.logging import RequestContextMiddleware, configure_logging

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Model Gateway",
        description="Provider-agnostic synchronous and durable asynchronous AI generation.",
        version=__version__,
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    application.include_router(router)
    application.mount("/metrics", make_asgi_app())
    return application


app = create_app()
