# Architecture

## Components

- **API:** authenticates, rate-limits, validates requests, and persists jobs.
- **PostgreSQL:** source of truth for job state and the transactional outbox.
- **Dispatcher:** safely publishes unsent outbox rows using concurrent `SKIP LOCKED` claims.
- **Redis Streams / TaskIQ:** durable delivery with consumer acknowledgements.
- **Worker:** leases jobs, executes routes, and persists normalized results.
- **KEDA:** scales worker pods from Redis Stream consumer-group lag.

The API, dispatcher, and worker scale independently. PostgreSQL remains authoritative; Redis
is transport, rate-limit state, and TaskIQ result storage.

## State machine

```text
queued ──claim──> running ──success──> succeeded
  │                  │
  └──cancel──────────┴──cancel───────> cancelled
                     │
                     └──terminal error──> failed
```

A running job has a lease. If a worker dies, a redelivered message may reclaim the job after
the lease expires. Terminal states cannot be claimed again. Success and failure updates compare both the attempt number and lease expiry; an expired or superseded worker cannot commit. There is no lease heartbeat, so the lease must exceed the complete route execution time, including retries and fallbacks. Provider calls can overlap after recovery; the fence protects the database result, not provider billing. Redis pending-message recovery is configured to wait beyond the database lease.

## Delivery guarantees

Job and outbox creation occur in one transaction. Dispatchers lock unpublished rows, publish
the job ID, and then mark the row. A crash before publication leaves the row pending. A crash
after publication but before marking creates a duplicate. The worker's atomic claim converts
duplicates into no-ops.

Redis Stream acknowledgements prevent a worker crash from silently discarding an in-flight
message. PostgreSQL and Redis persistence, replication, backups, and failover must still be
configured by the operator.

## Adding a provider

Implement `ModelProvider.generate(request, model) -> GenerationResult` and register it in
`gateway.runtime.get_providers`. Normalize tokens, latency, model identity, and provider
request ID. Raise `ProviderError(transient=True)` only for retryable transport, timeout,
rate-limit, or server failures. Authentication, validation, and other permanent failures
should not be retried.

Never log credentials or full sensitive prompts. Provider SDK retries must be disabled when
the executor owns retry policy, otherwise multiplicative retry storms are possible.

## Cost accounting

The executor calculates cost with Decimal arithmetic after normalizing token usage. Routes
hold per-million-token rates, allowing negotiated or regional pricing. Zero is the safe
default: an unset rate means “cost not configured,” not “the provider is free.”
