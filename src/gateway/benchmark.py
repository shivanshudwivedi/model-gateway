"""Async load generator with deterministic reconciliation."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


async def run(
    base_url: str, api_key: str, jobs: int, concurrency: int, timeout_seconds: float
) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(concurrency)
    headers = {"X-API-Key": api_key}
    accepted: list[str] = []
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30) as client:

        async def submit(index: int) -> None:
            async with semaphore:
                response = await client.post(
                    "/v1/jobs",
                    headers={"Idempotency-Key": f"benchmark-{index}"},
                    json={
                        "messages": [{"role": "user", "content": f"job-{index}"}],
                        "route": "deterministic",
                    },
                )
                response.raise_for_status()
                accepted.append(response.json()["id"])

        await asyncio.gather(*(submit(index) for index in range(jobs)))
        deadline = time.monotonic() + timeout_seconds
        statuses: Counter[str] = Counter()
        pending = set(accepted)
        while pending and time.monotonic() < deadline:
            batch = list(pending)[:concurrency]
            responses = await asyncio.gather(
                *(client.get(f"/v1/jobs/{job_id}") for job_id in batch)
            )
            for job_id, response in zip(batch, responses, strict=True):
                response.raise_for_status()
                state = response.json()["status"]
                if state in {"succeeded", "failed", "cancelled"}:
                    pending.remove(job_id)
                    statuses[state] += 1
            if pending:
                await asyncio.sleep(0.1)

    elapsed = time.perf_counter() - started
    return {
        "submitted": jobs,
        "accepted": len(accepted),
        "terminal": sum(statuses.values()),
        "pending_at_timeout": len(pending),
        "lost": jobs - len(accepted),
        "statuses": dict(statuses),
        "elapsed_seconds": elapsed,
        "throughput_jobs_per_second": jobs / elapsed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="local-development-key")
    parser.add_argument("--jobs", type=int, default=10_000)
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(
        run(args.base_url, args.api_key, args.jobs, args.concurrency, args.timeout)
    )
    rendered = json.dumps(result, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if result["lost"] or result["pending_at_timeout"] or result["statuses"].get("failed", 0):
        raise SystemExit(1)
