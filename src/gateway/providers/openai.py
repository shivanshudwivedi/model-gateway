"""OpenAI Responses API adapter."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from openai import AsyncOpenAI

from gateway.providers.base import ProviderError
from gateway.schemas import GenerationRequest, GenerationResult, Usage


class OpenAIProvider:
    name = "openai"

    def __init__(self, client: AsyncOpenAI | None = None) -> None:
        self.client = client or AsyncOpenAI(max_retries=0, timeout=60)

    async def generate(self, request: GenerationRequest, model: str) -> GenerationResult:
        instructions = "\n\n".join(
            message.content for message in request.messages if message.role == "system"
        )
        inputs: list[dict[str, Any]] = [
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role != "system"
        ]
        kwargs: dict[str, Any] = {
            "model": model,
            "input": inputs,
            "max_output_tokens": request.max_output_tokens,
        }
        if instructions:
            kwargs["instructions"] = instructions
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature

        started = perf_counter()
        try:
            response = await self.client.responses.create(**kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            transient = status in {408, 409, 429} or (isinstance(status, int) and status >= 500)
            raise ProviderError(str(exc), transient=transient, code="openai_error") from exc
        usage = getattr(response, "usage", None)
        return GenerationResult(
            text=response.output_text,
            provider=self.name,
            model=model,
            usage=Usage(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            ),
            latency_ms=(perf_counter() - started) * 1000,
            provider_request_id=response.id,
        )
