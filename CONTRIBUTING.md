# Contributing

Create a virtual environment, install the development extras, and run:

```bash
make check
docker compose config --quiet
```

Changes to delivery, leases, cancellation, idempotency, retries, or state transitions require
tests for both the success path and relevant race/failure path. Never add live provider calls
to the unit suite, commit secrets, or claim benchmark scale without a retained reconciliation
report and environment description.
