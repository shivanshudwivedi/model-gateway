# Benchmark results

## Local integration reconciliation — 1,000 jobs

Run on 2026-07-31 while validating the initial implementation:

```json
{
  "submitted": 1000,
  "accepted": 1000,
  "terminal": 1000,
  "pending_at_timeout": 0,
  "lost": 0,
  "statuses": {
    "succeeded": 1000
  },
  "elapsed_seconds": 11.88647091697203,
  "throughput_jobs_per_second": 84.12925981017256
}
```

Environment:

- one API process on macOS
- one dispatcher process
- one TaskIQ worker process with up to 10 concurrent async tasks
- PostgreSQL 13 and Redis 7 in local Docker containers
- deterministic provider
- 100 concurrent benchmark clients

This result proves reconciliation for this run only. It is not presented as a one-million-job
result. Use the included `gateway-benchmark --jobs 1000000` command on the intended deployment
and retain its report before making that larger claim.
