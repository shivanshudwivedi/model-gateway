"""Transactional-outbox relay from PostgreSQL to TaskIQ."""

from __future__ import annotations

import asyncio
from contextlib import suppress

import structlog

from gateway.broker import broker
from gateway.config import get_settings
from gateway.db import SessionFactory
from gateway.logging import configure_logging
from gateway.repository import JobRepository
from gateway.tasks import process_job

logger = structlog.get_logger()


async def dispatch_once() -> int:
    settings = get_settings()
    async with SessionFactory() as session:
        repository = JobRepository(session)
        published = 0
        for _ in range(settings.dispatcher_batch_size):
            events = await repository.unpublished(1)
            if not events:
                break
            event = events[0]
            try:
                await process_job.kiq(str(event.job_id))
                await repository.mark_published(event)
                published += 1
            except Exception as exc:
                await repository.mark_publish_error(event, str(exc))
                await logger.aerror("outbox_publish_failed", event_id=str(event.id), error=str(exc))
        return published


async def run_dispatcher() -> None:
    settings = get_settings()
    await broker.startup()
    try:
        while True:
            published = await dispatch_once()
            if published == 0:
                await asyncio.sleep(settings.dispatcher_poll_seconds)
    finally:
        await broker.shutdown()


def main() -> None:
    configure_logging(get_settings().log_level)
    with suppress(KeyboardInterrupt):
        asyncio.run(run_dispatcher())
