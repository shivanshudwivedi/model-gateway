"""Provider contract and normalized errors."""

from __future__ import annotations

from typing import Protocol

from gateway.schemas import GenerationRequest, GenerationResult


class ProviderError(Exception):
    def __init__(self, message: str, *, transient: bool = False, code: str = "provider_error"):
        super().__init__(message)
        self.transient = transient
        self.code = code


class ModelProvider(Protocol):
    name: str

    async def generate(self, request: GenerationRequest, model: str) -> GenerationResult: ...
