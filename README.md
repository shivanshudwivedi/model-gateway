# Model Gateway & Async Job Platform

A production-minded, provider-agnostic AI gateway built with FastAPI, PostgreSQL, Redis
Streams, TaskIQ, Docker, and Kubernetes.

It exposes low-latency synchronous generation and durable asynchronous jobs while enforcing
API-key authentication, distributed rate limits, retries, provider fallbacks, idempotency,
and complete request accounting.

## Capabilities

- Provider-neutral request and response contracts
- Synchronous `POST /v1/generate` and durable `POST /v1/jobs`
- PostgreSQL-backed state, token usage, latency, errors, and cost
- Transactional outbox so committed jobs cannot disappear before queue publication
- Redis Stream TaskIQ broker with consumer acknowledgements
- Leased, idempotent worker claims for safe at-least-once delivery
- Bounded exponential retry of transient failures and ordered provider fallbacks
- Atomic Redis rate limiting shared across API replicas
- Deterministic provider for tests, demos, and fault injection
- OpenAI Responses API and generic HTTP provider adapters
- JSON structured logs, request IDs, health probes, and Prometheus metrics
- Docker Compose development stack
- Kubernetes workloads, disruption budget, security contexts, and KEDA queue-lag autoscaling
- Reconciliation benchmark for proving accepted-to-terminal job counts

## Reliability model

```text
API transaction                 Dispatcher                 Worker
┌──────────────┐                ┌──────────────┐           ┌──────────────┐
│ INSERT job   │                │ lock outbox  │           │ lease/claim  │
│ INSERT event │──PostgreSQL───>│ publish      │──Stream──>│ call route   │
│ COMMIT       │                │ mark sent    │           │ store result │
└──────────────┘                └──────────────┘           └──────────────┘
```

The outbox closes the commit/publish gap. A dispatcher crash after publication can create a
duplicate delivery, but cannot lose a job. Workers atomically claim only queued jobs or jobs
whose lease expired, so duplicate messages are harmless. Redis Streams retain unacknowledged
work for recovery after worker termination.

This provides **at-least-once delivery with idempotent execution**, not magical exactly-once
delivery. External providers may still accept a request immediately before a network failure;
use provider-supported idempotency keys when extending adapters for side-effecting operations.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

The stack starts PostgreSQL, persistent Redis, runs migrations, and launches the API,
transactional-outbox dispatcher, and workers.

Submit a deterministic job:

```bash
curl -sS http://localhost:8000/v1/jobs \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: local-development-key' \
  -H 'Idempotency-Key: demo-001' \
  -d '{
    "route": "deterministic",
    "messages": [{"role": "user", "content": "hello gateway"}]
  }'
```

Fetch the returned job ID:

```bash
curl -sS http://localhost:8000/v1/jobs/JOB_ID \
  -H 'X-API-Key: local-development-key'
```

Or make a synchronous request:

```bash
curl -sS http://localhost:8000/v1/generate \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: local-development-key' \
  -d '{
    "route": "deterministic",
    "messages": [{"role": "user", "content": "hello gateway"}]
  }'
```

OpenAPI documentation is available at <http://localhost:8000/docs> and Prometheus metrics at
<http://localhost:8000/metrics/>.

## API behavior

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/generate` | Execute through the selected route and return the result |
| `POST /v1/jobs` | Persist a job and return `202 Accepted` |
| `GET /v1/jobs/{id}` | Read status, result, usage, latency, cost, or error |
| `POST /v1/jobs/{id}/cancel` | Cancel a queued or running job |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | PostgreSQL and Redis readiness |
| `GET /metrics/` | Prometheus metrics |

All business endpoints require `X-API-Key`. Submit an `Idempotency-Key` on job creation:

- Reusing the key with the same canonical request returns the original job.
- Reusing the key with a different request returns HTTP `409`.
- Keys are scoped to the authenticated tenant.

Rate-limit responses include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After`
where applicable.

## Routing and providers

Routes live in `config/routes.yaml`:

```yaml
routes:
  general:
    model: gpt-5.6
    providers: [openai, deterministic]
    input_cost_per_million: "0"
    output_cost_per_million: "0"
```

Providers are attempted in order. A transient error is retried with bounded exponential
backoff; exhausted or permanent failures move to the next provider. Keep pricing in deployment
configuration and update it from your contract—source code deliberately does not claim that a
historical public price remains correct.

The OpenAI adapter uses the Responses API. Set `OPENAI_API_KEY` to enable it. The deterministic
provider supports `metadata.test_mode`: `echo`, `reverse`, `fixed`, `transient_error`, and
`permanent_error`.

The generic `HTTPProvider` expects:

```json
{
  "text": "response",
  "model": "optional-model",
  "usage": {"input_tokens": 12, "output_tokens": 4},
  "request_id": "optional-provider-id"
}
```

See [docs/architecture.md](docs/architecture.md) to add a provider safely.

## Benchmark and the “no lost jobs” claim

Start the stack, then run:

```bash
gateway-benchmark --jobs 1000000 --concurrency 500 \
  --timeout 7200 --output benchmark-results/one-million.json
```

The benchmark uses unique idempotency keys, records every accepted ID, polls until every job
reaches a terminal state, and fails if accepted counts differ, jobs remain pending at timeout,
or any job fails. Throughput depends on hardware, replica counts, PostgreSQL/Redis sizing, and
provider latency. Do not claim the one-million result without retaining the generated report
and infrastructure details.

The initial verified 1,000-job reconciliation is recorded in
[docs/benchmarks.md](docs/benchmarks.md).

## Kubernetes

`k8s/platform.yaml` includes API, dispatcher, worker, migration job, service, pod disruption
budget, restricted container security contexts, and a KEDA `redis-streams` scaler based on
consumer-group lag. `k8s/dev-dependencies.yaml` adds development-only PostgreSQL and Redis.

Before deployment:

1. Publish the image and replace the example image reference.
2. Replace the example Secret or integrate a secret controller.
3. Point the ConfigMap at managed PostgreSQL and Redis.
4. Apply the migration Job and wait for completion.
5. Install KEDA, then apply the platform resources.
6. Configure ingress, TLS, network policy, backups, alerts, and provider pricing for your environment.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
make check
```

See [docs/operations.md](docs/operations.md) for failure recovery and production rollout.

## Security

The included API-key mechanism is suitable for a bounded internal deployment. Internet-facing
use should place an identity-aware gateway in front, rotate keys through a secret manager, and
apply tenant-specific quotas. Request and result bodies may contain sensitive information and
are stored in PostgreSQL; apply encryption, retention, and access controls accordingly.

## License

MIT
