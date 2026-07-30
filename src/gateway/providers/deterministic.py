"""Credential-free provider for testing and operational smoke checks."""

from __future__ import annotations

from time import perf_counter

from gateway.providers.base import ProviderError
from gateway.schemas import GenerationRequest, GenerationResult, Usage


class DeterministicProvider:
    name = "deterministic"

    async def generate(self, request: GenerationRequest, model: str) -> GenerationResult:
        started = perf_counter()
        mode = str(request.metadata.get("test_mode", "echo"))
        content = request.messages[-1].content
        if mode == "echo":
            text = content
        elif mode == "reverse":
            text = content[::-1]
        elif mode == "fixed":
            text = str(request.metadata.get("fixed_response", "deterministic response"))
        elif mode == "transient_error":
            raise ProviderError("injected transient failure", transient=True, code="injected")
        elif mode == "permanent_error":
            raise ProviderError("injected permanent failure", code="injected")
        else:
            raise ProviderError(f"unknown deterministic test mode: {mode}", code="bad_test_mode")
        return GenerationResult(
            text=text,
            provider=self.name,
            model=model,
            usage=Usage(input_tokens=len(content.split()), output_tokens=len(text.split())),
            latency_ms=(perf_counter() - started) * 1000,
        )
