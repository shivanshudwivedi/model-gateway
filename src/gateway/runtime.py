"""Lazily constructed process-local runtime services."""

from __future__ import annotations

from functools import lru_cache

from gateway.config import get_settings
from gateway.executor import Executor
from gateway.providers.base import ModelProvider
from gateway.providers.deterministic import DeterministicProvider
from gateway.routing import Router


@lru_cache
def get_router() -> Router:
    settings = get_settings()
    return Router.from_yaml(settings.routes_config, settings.default_route)


@lru_cache
def get_providers() -> dict[str, ModelProvider]:
    providers: dict[str, ModelProvider] = {"deterministic": DeterministicProvider()}
    try:
        from gateway.providers.openai import OpenAIProvider

        providers["openai"] = OpenAIProvider()
    except Exception:
        # Missing credentials should not prevent non-OpenAI routes from starting.
        pass
    return providers


@lru_cache
def get_executor() -> Executor:
    settings = get_settings()
    return Executor(get_router(), get_providers(), settings.job_max_attempts)
