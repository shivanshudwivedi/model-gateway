"""Durable job state transitions and transactional outbox operations."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db import Job, OutboxEvent
from gateway.schemas import GenerationRequest, GenerationResult, JobStatus


class IdempotencyConflictError(Exception):
    """An idempotency key was reused with a different request body."""


def request_digest(request: GenerationRequest) -> str:
    canonical = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, tenant_id: str, request: GenerationRequest, idempotency_key: str | None
    ) -> tuple[Job, bool]:
        digest = request_digest(request)
        if idempotency_key:
            existing = await self._by_idempotency(tenant_id, idempotency_key)
            if existing:
                if existing.request_hash != digest:
                    raise IdempotencyConflictError
                return existing, True

        job = Job(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            request_hash=digest,
            request_payload=request.model_dump(mode="json"),
        )
        job.outbox = OutboxEvent()
        self.session.add(job)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            if not idempotency_key:
                raise
            existing = await self._by_idempotency(tenant_id, idempotency_key)
            if existing is None or existing.request_hash != digest:
                raise IdempotencyConflictError from None
            return existing, True
        await self.session.refresh(job)
        return job, False

    async def get(self, job_id: UUID, tenant_id: str | None = None) -> Job | None:
        statement = select(Job).where(Job.id == job_id)
        if tenant_id:
            statement = statement.where(Job.tenant_id == tenant_id)
        job: Job | None = await self.session.scalar(statement)
        return job

    async def claim(self, job_id: UUID, lease_seconds: int) -> Job | None:
        now = datetime.now(UTC)
        statement = (
            select(Job)
            .where(
                Job.id == job_id,
                or_(
                    Job.status == JobStatus.QUEUED,
                    (Job.status == JobStatus.RUNNING) & (Job.lease_expires_at < now),
                ),
            )
            .with_for_update()
        )
        job = await self.session.scalar(statement)
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.attempt += 1
        await self.session.commit()
        return job

    async def succeed(self, job: Job, result: GenerationResult) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job.id,
                Job.status == JobStatus.RUNNING,
                Job.attempt == job.attempt,
                Job.lease_expires_at > datetime.now(UTC),
            )
            .values(
                status=JobStatus.SUCCEEDED,
                result_payload=result.model_dump(mode="json"),
                provider=result.provider,
                model=result.model,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=result.latency_ms,
                cost_usd=result.cost_usd,
                completed_at=datetime.now(UTC),
                lease_expires_at=None,
            )
        )
        outcome = cast(
            CursorResult[Any],
            await self.session.execute(statement.execution_options(synchronize_session=False)),
        )
        await self.session.commit()
        await self.session.refresh(job)
        return bool(outcome.rowcount)

    async def fail(self, job: Job, code: str, message: str) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job.id,
                Job.status == JobStatus.RUNNING,
                Job.attempt == job.attempt,
                Job.lease_expires_at > datetime.now(UTC),
            )
            .values(
                status=JobStatus.FAILED,
                error_code=code,
                error_message=message[:4000],
                completed_at=datetime.now(UTC),
                lease_expires_at=None,
            )
        )
        outcome = cast(
            CursorResult[Any],
            await self.session.execute(statement.execution_options(synchronize_session=False)),
        )
        await self.session.commit()
        await self.session.refresh(job)
        return bool(outcome.rowcount)

    async def cancel(self, job: Job) -> bool:
        statement = (
            update(Job)
            .where(Job.id == job.id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
            .values(
                status=JobStatus.CANCELLED,
                completed_at=datetime.now(UTC),
                lease_expires_at=None,
            )
        )
        outcome = cast(
            CursorResult[Any],
            await self.session.execute(statement.execution_options(synchronize_session=False)),
        )
        await self.session.commit()
        await self.session.refresh(job)
        return bool(outcome.rowcount)

    async def unpublished(self, limit: int) -> list[OutboxEvent]:
        statement = (
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.scalars(statement)).all())

    async def mark_published(self, event: OutboxEvent) -> None:
        event.published_at = datetime.now(UTC)
        event.attempts += 1
        event.last_error = None
        await self.session.commit()

    async def mark_publish_error(self, event: OutboxEvent, error: str) -> None:
        event.attempts += 1
        event.last_error = error[:4000]
        await self.session.commit()

    async def _by_idempotency(self, tenant_id: str, key: str) -> Job | None:
        job: Job | None = await self.session.scalar(
            select(Job).where(Job.tenant_id == tenant_id, Job.idempotency_key == key)
        )
        return job
