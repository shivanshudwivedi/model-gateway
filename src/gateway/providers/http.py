"""Generic HTTP provider adapter using the gateway's neutral contract."""

from __future__ import annotations

import os
from time import perf_counter

import httpx

from gateway.providers.base import ProviderError
from gateway.schemas import GenerationRequest, GenerationResult, Usage


class HTTPProvider:
    def __init__(self, name: str, base_url: str, api_key_env: str | None = None) -> None:
        self.name = name
        headers = {}
        if api_key_env and (key := os.getenv(api_key_env)):
            headers["Authorization"] = f"Bearer {key}"
        self.client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60)

    async def generate(self, request: GenerationRequest, model: str) -> GenerationResult:
        started = perf_counter()
        try:
            response = await self.client.post(
                "/generate", json={"model": model, **request.model_dump(mode="json")}
            )
            response.raise_for_status()
            body = response.json()
            usage = Usage.model_validate(body.get("usage", {}))
            return GenerationResult(
                text=str(body["text"]),
                provider=self.name,
                model=str(body.get("model", model)),
                usage=usage,
                latency_ms=(perf_counter() - started) * 1000,
                provider_request_id=body.get("request_id"),
            )
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            transient = status in {408, 409, 429} or (isinstance(status, int) and status >= 500)
            raise ProviderError(str(exc), transient=transient, code="http_provider_error") from exc
