# Operations guide

## Deployment order

1. Provision PostgreSQL with automated backups and Redis 7+ with persistence.
2. Publish an immutable image tag or digest.
3. Configure secrets, routes, prices, limits, and connection URLs.
4. Run `alembic upgrade head` as a one-off job.
5. Deploy API and dispatcher.
6. Deploy workers and KEDA scaler.
7. Run deterministic smoke requests and a reconciliation benchmark.

## Key alerts

- oldest unpublished outbox event age
- queued and running jobs by age
- expired running leases
- Redis consumer-group lag and pending entries
- provider error and rate-limit rates
- p95/p99 provider latency
- failed-job ratio and worker restart count
- PostgreSQL connection saturation

## Failure recovery

**Dispatcher unavailable:** jobs remain queued in PostgreSQL. Restart dispatchers; outbox
rows resume automatically.

**Redis unavailable:** dispatch attempts remain unpublished with the last error. Submission rate limiting also depends on Redis, so new submissions can fail while it is unavailable. PostgreSQL retains previously committed jobs; readiness returns HTTP 503.

**Worker killed:** the Stream message remains unacknowledged. After redelivery and lease
expiry, another worker reclaims it.

**Provider outage:** transient calls retry, then routes fall back. If all providers fail, the
job is terminally failed with a normalized code.

**Stuck lease:** verify the original worker is gone, then allow the configured lease to
expire. Redeliver/re-publish the job ID if the broker message was administratively removed.

## Safe shutdown

Give workers at least `JOB_LEASE_SECONDS` of termination grace when provider calls can run
that long. Dispatchers are stateless and may stop between records. API pods should stop
accepting traffic before termination through readiness removal.

## Benchmark interpretation

The benchmark verifies application-level reconciliation, not infrastructure durability under
every failure mode. Record commit SHA, image digest, instance sizes, database/Redis settings,
replica counts, duration, and the result JSON. Add controlled pod, Redis, and dispatcher
failures when qualifying production recovery behavior.

## Lease sizing and sensitive data

Set `JOB_LEASE_SECONDS` above the worst-case execution duration across all provider retries and fallbacks. There is no heartbeat. Late completion is discarded, and recovery can call the provider again; this may create additional charges. Do not use these adapters for irreversible external actions without a provider-supported idempotency contract.

Prompts, metadata, results and provider error strings can be sensitive. The service does not implement a redaction pipeline, database RLS, RBAC, per-tenant encryption or automatic retention. Keep `/docs`, `/metrics/` and dependencies behind trusted network boundaries. Set explicit payload limits, retention, credentials and backup policies at deployment.

## Dependency compatibility

TaskIQ is constrained to the 0.12 release family: TaskIQ 0.13 removed compatibility helpers used by the Redis integration selected on Python 3.11. CI imports the actual worker entry point so a passing core test suite cannot hide a broken worker installation.
