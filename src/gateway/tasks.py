"""Idempotent TaskIQ worker tasks."""

from __future__ import annotations

from uuid import UUID

import structlog

from gateway.broker import broker
from gateway.config import get_settings
from gateway.db import SessionFactory
from gateway.executor import ExecutionError
from gateway.repository import JobRepository
from gateway.runtime import get_executor
from gateway.schemas import GenerationRequest

logger = structlog.get_logger()


@broker.task(task_name="gateway.process_job")
async def process_job(job_id: str) -> None:
    settings = get_settings()
    async with SessionFactory() as session:
        repository = JobRepository(session)
        job = await repository.claim(UUID(job_id), settings.job_lease_seconds)
        if job is None:
            await logger.ainfo("job_duplicate_or_terminal", job_id=job_id)
            return
        try:
            request = GenerationRequest.model_validate(job.request_payload)
            result = await get_executor().execute(request)
            committed = await repository.succeed(job, result)
            await logger.ainfo(
                "job_succeeded" if committed else "job_completion_discarded",
                job_id=job_id,
                provider=result.provider,
                model=result.model,
                latency_ms=result.latency_ms,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cost_usd=str(result.cost_usd),
            )
        except ExecutionError as exc:
            await repository.fail(job, exc.code, str(exc))
            await logger.aerror("job_failed", job_id=job_id, code=exc.code, error=str(exc))
        except Exception as exc:
            await repository.fail(job, "internal_error", str(exc))
            await logger.aexception("job_failed", job_id=job_id, error=str(exc))
