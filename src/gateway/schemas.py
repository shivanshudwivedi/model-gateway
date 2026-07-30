"""Public API and provider-neutral data contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class GenerationRequest(StrictModel):
    messages: list[Message] = Field(min_length=1, max_length=100)
    route: str | None = None
    model: str | None = None
    max_output_tokens: int = Field(default=1024, ge=1, le=100_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Usage(StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class GenerationResult(StrictModel):
    text: str
    provider: str
    model: str
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = Field(ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    provider_request_id: str | None = None


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobResponse(StrictModel):
    id: UUID
    status: JobStatus
    request: GenerationRequest
    result: GenerationResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempt: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobAccepted(StrictModel):
    id: UUID
    status: JobStatus
    status_url: str
    deduplicated: bool = False


class HealthResponse(StrictModel):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, bool]
