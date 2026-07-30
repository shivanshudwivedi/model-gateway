"""Versioned FastAPI routes."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.config import Settings, get_settings
from gateway.db import Job, get_session
from gateway.executor import ExecutionError, Executor
from gateway.rate_limit import RedisRateLimiter
from gateway.repository import IdempotencyConflictError, JobRepository
from gateway.runtime import get_executor
from gateway.schemas import (
    GenerationRequest,
    GenerationResult,
    HealthResponse,
    JobAccepted,
    JobResponse,
    JobStatus,
    Usage,
)

router = APIRouter()
SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ExecutorDep = Annotated[Executor, Depends(get_executor)]


async def authenticate(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header()] = None,
) -> str:
    if not x_api_key or not any(
        _constant_time_equal(x_api_key, candidate) for candidate in settings.api_keys
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
    return hashlib.sha256(x_api_key.encode()).hexdigest()[:32]


TenantDep = Annotated[str, Depends(authenticate)]


async def enforce_rate_limit(
    request: Request,
    response: Response,
    tenant_id: TenantDep,
    settings: SettingsDep,
) -> None:
    redis: Redis = request.app.state.redis
    decision = await RedisRateLimiter(
        redis, settings.rate_limit_requests, settings.rate_limit_window_seconds
    ).check(tenant_id)
    response.headers["X-RateLimit-Limit"] = str(decision.limit)
    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers={"Retry-After": str(decision.retry_after)},
        )


RateLimitDep = Annotated[None, Depends(enforce_rate_limit)]


@router.post(
    "/v1/jobs",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(enforce_rate_limit)],
)
async def create_job(
    payload: GenerationRequest,
    request: Request,
    session: SessionDep,
    tenant_id: TenantDep,
    idempotency_key: Annotated[str | None, Header(max_length=255)] = None,
) -> JobAccepted:
    repository = JobRepository(session)
    try:
        job, deduplicated = await repository.create(tenant_id, payload, idempotency_key)
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="idempotency key was already used with a different request",
        ) from exc
    return JobAccepted(
        id=job.id,
        status=job.status,
        status_url=str(request.url_for("get_job", job_id=str(job.id))),
        deduplicated=deduplicated,
    )


@router.get("/v1/jobs/{job_id}", response_model=JobResponse, name="get_job")
async def get_job(job_id: UUID, session: SessionDep, tenant_id: TenantDep) -> JobResponse:
    job = await JobRepository(session).get(job_id, tenant_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return _job_response(job)


@router.post("/v1/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: UUID, session: SessionDep, tenant_id: TenantDep) -> JobResponse:
    repository = JobRepository(session)
    job = await repository.get(job_id, tenant_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    if not await repository.cancel(job):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"job in {job.status} state cannot be cancelled",
        )
    return _job_response(job)


@router.post(
    "/v1/generate",
    response_model=GenerationResult,
    dependencies=[Depends(enforce_rate_limit)],
)
async def generate(
    payload: GenerationRequest,
    executor: ExecutorDep,
    tenant_id: TenantDep,
) -> GenerationResult:
    del tenant_id
    try:
        return await executor.execute(payload)
    except (ExecutionError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=HealthResponse, include_in_schema=False)
async def ready(request: Request, session: SessionDep) -> HealthResponse:
    checks = {"postgres": False, "redis": False}
    with suppress(Exception):
        checks["postgres"] = (await session.scalar(text("SELECT 1"))) == 1
    with suppress(Exception):
        checks["redis"] = bool(await request.app.state.redis.ping())
    return HealthResponse(
        status="ok" if all(checks.values()) else "degraded",
        version=request.app.version,
        checks=checks,
    )


def _job_response(job: Job) -> JobResponse:
    result = None
    if job.result_payload:
        result = GenerationResult.model_validate(job.result_payload)
    elif job.status == JobStatus.SUCCEEDED:
        result = GenerationResult(
            text="",
            provider=job.provider or "",
            model=job.model or "",
            usage=Usage(input_tokens=job.input_tokens, output_tokens=job.output_tokens),
            latency_ms=float(job.latency_ms or 0),
            cost_usd=Decimal(str(job.cost_usd or 0)),
        )
    return JobResponse(
        id=job.id,
        status=job.status,
        request=GenerationRequest.model_validate(job.request_payload),
        result=result,
        error_code=job.error_code,
        error_message=job.error_message,
        attempt=job.attempt,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def _constant_time_equal(left: str, right: str) -> bool:
    return hashlib.sha256(left.encode()).digest() == hashlib.sha256(right.encode()).digest()
