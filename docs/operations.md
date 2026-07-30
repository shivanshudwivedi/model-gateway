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

**Redis unavailable:** dispatch attempts remain unpublished with the last error. The API can
still accept jobs while PostgreSQL is healthy, but readiness is degraded.

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
