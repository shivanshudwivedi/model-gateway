"""Provider retries, fallbacks, normalized costing, and metrics."""

from __future__ import annotations

import asyncio

import structlog
from prometheus_client import Counter, Histogram

from gateway.providers.base import ModelProvider, ProviderError
from gateway.routing import Router
from gateway.schemas import GenerationRequest, GenerationResult

logger = structlog.get_logger()
REQUESTS = Counter("gateway_provider_requests_total", "Provider calls", ["provider", "status"])
LATENCY = Histogram("gateway_provider_latency_seconds", "Provider latency", ["provider"])


class ExecutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Executor:
    def __init__(
        self, router: Router, providers: dict[str, ModelProvider], max_attempts: int = 3
    ) -> None:
        self.router = router
        self.providers = providers
        self.max_attempts = max_attempts

    async def execute(self, request: GenerationRequest) -> GenerationResult:
        route = self.router.resolve(request)
        errors: list[str] = []
        for provider_name in route.providers:
            provider = self.providers.get(provider_name)
            if provider is None:
                errors.append(f"{provider_name}: not configured")
                continue
            for attempt in range(1, self.max_attempts + 1):
                try:
                    with LATENCY.labels(provider_name).time():
                        result = await provider.generate(request, route.model)
                    result.cost_usd = route.price(result)
                    REQUESTS.labels(provider_name, "success").inc()
                    return result
                except ProviderError as exc:
                    REQUESTS.labels(provider_name, "error").inc()
                    errors.append(f"{provider_name}[{attempt}]: {exc}")
                    await logger.awarning(
                        "provider_attempt_failed",
                        provider=provider_name,
                        attempt=attempt,
                        transient=exc.transient,
                        error=str(exc),
                    )
                    if not exc.transient or attempt == self.max_attempts:
                        break
                    await asyncio.sleep(min(0.25 * 2 ** (attempt - 1), 2.0))
        raise ExecutionError("all_providers_failed", "; ".join(errors))
