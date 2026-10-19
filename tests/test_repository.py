from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db import Base
from gateway.repository import IdempotencyConflictError, JobRepository, request_digest
from gateway.schemas import (
    GenerationRequest,
    GenerationResult,
    JobStatus,
    Message,
)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


def payload(text: str = "hello") -> GenerationRequest:
    return GenerationRequest(messages=[Message(role="user", content=text)])


@pytest.mark.asyncio
async def test_create_is_idempotent_and_creates_outbox(session) -> None:
    repository = JobRepository(session)
    first, duplicate = await repository.create("tenant", payload(), "key")
    second, duplicate_second = await repository.create("tenant", payload(), "key")
    assert not duplicate
    assert duplicate_second
    assert first.id == second.id
    events = await repository.unpublished(10)
    assert len(events) == 1
    assert events[0].job_id == first.id


@pytest.mark.asyncio
async def test_idempotency_conflict(session) -> None:
    repository = JobRepository(session)
    await repository.create("tenant", payload("one"), "key")
    with pytest.raises(IdempotencyConflictError):
        await repository.create("tenant", payload("two"), "key")


@pytest.mark.asyncio
async def test_job_state_transitions_and_expired_lease(session) -> None:
    repository = JobRepository(session)
    job, _ = await repository.create("tenant", payload(), None)
    claimed = await repository.claim(job.id, 60)
    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING
    assert claimed.attempt == 1
    assert await repository.claim(job.id, 60) is None

    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    reclaimed = await repository.claim(job.id, 60)
    assert reclaimed is not None
    assert reclaimed.attempt == 2

    await repository.succeed(
        reclaimed,
        GenerationResult(text="ok", provider="test", model="m", latency_ms=2),
    )
    assert reclaimed.status == JobStatus.SUCCEEDED
    assert await repository.claim(job.id, 60) is None


@pytest.mark.asyncio
async def test_failure_cancellation_and_outbox_updates(session) -> None:
    repository = JobRepository(session)
    failed, _ = await repository.create("tenant", payload("fail"), None)
    claimed = await repository.claim(failed.id, 60)
    assert claimed is not None
    await repository.fail(claimed, "test_error", "details")
    assert claimed.status == JobStatus.FAILED
    assert claimed.error_code == "test_error"

    cancelled, _ = await repository.create("tenant", payload("cancel"), None)
    assert await repository.cancel(cancelled)
    assert not await repository.cancel(cancelled)

    events = await repository.unpublished(10)
    await repository.mark_publish_error(events[0], "redis down")
    assert events[0].attempts == 1
    await repository.mark_published(events[0])
    assert events[0].published_at is not None


def test_request_digest_is_canonical() -> None:
    assert request_digest(payload()) == request_digest(payload())


@pytest.mark.parametrize("completion", ["success", "failure"])
async def test_reclaimed_lease_rejects_stale_worker(session, completion) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    repository = JobRepository(session)
    job, _ = await repository.create("tenant", payload(), None)
    stale = await repository.claim(job.id, 60)
    assert stale is not None
    stale_attempt = stale.attempt
    stale.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()

    # A different session is essential: the original worker retains attempt 1.
    async with AsyncSession(session.bind, expire_on_commit=False) as other:
        current_repository = JobRepository(other)
        current = await current_repository.claim(job.id, 60)
        assert current is not None and current.attempt == stale_attempt + 1
        if completion == "success":
            changed = await repository.succeed(
                stale, GenerationResult(text="stale", provider="test", model="m", latency_ms=1)
            )
        else:
            changed = await repository.fail(stale, "stale", "obsolete failure")
        assert not changed
        await other.refresh(current)
        assert current.status == JobStatus.RUNNING
        assert current.result_payload is None and current.error_code is None
        assert await current_repository.succeed(
            current, GenerationResult(text="current", provider="test", model="m", latency_ms=1)
        )
        await session.refresh(stale)
        assert stale.result_payload["text"] == "current"


async def test_expired_worker_cannot_commit_without_reclaim(session) -> None:
    repository = JobRepository(session)
    job, _ = await repository.create("tenant", payload(), None)
    claimed = await repository.claim(job.id, 60)
    assert claimed is not None
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert not await repository.succeed(
        claimed, GenerationResult(text="late", provider="test", model="m", latency_ms=1)
    )
    assert not await repository.fail(claimed, "late", "late failure")
    assert claimed.status == JobStatus.RUNNING
