# Operational walkthrough: accept, finish and deduplicate a job

Prerequisites: the repository's Compose stack is running on port 8000, and the development API key has not been changed. Commands below run in a second terminal at the repository root using Python 3.11+ and only its standard library.

```bash
python - <<'PY'
import json
import os
import time
import urllib.error
import urllib.request
import uuid

base = os.environ.get('GATEWAY_URL', 'http://localhost:8000').rstrip('/')
key = os.environ.get('API_KEY', 'local-development-key')
identity = 'walkthrough-' + str(uuid.uuid4())
body = {'route': 'deterministic', 'messages': [{'role': 'user', 'content': 'hello gateway'}]}

def call(path, payload=None, identity=None):
    headers = {'X-API-Key': key}
    if identity:
        headers['Idempotency-Key'] = identity
    data = None if payload is None else json.dumps(payload).encode()
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(base + path, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)

accepted = call('/v1/jobs', body, identity)
repeated = call('/v1/jobs', body, identity)
assert repeated['id'] == accepted['id'] and repeated['deduplicated']
print('Accepted and deduplicated:', accepted['id'])

changed = {**body, 'messages': [{'role': 'user', 'content': 'different request'}]}
try:
    call('/v1/jobs', changed, identity)
except urllib.error.HTTPError as error:
    assert error.code == 409, error.code
    print('Conflicting reuse rejected: HTTP 409')
else:
    raise AssertionError('Changed body was incorrectly accepted')

for _ in range(60):
    job = call('/v1/jobs/' + accepted['id'])
    if job['status'] in ('succeeded', 'failed', 'cancelled'):
        break
    time.sleep(1)
else:
    raise TimeoutError('Job did not finish; check dispatcher and worker logs')
assert job['status'] == 'succeeded', job
print('Result:', job['result']['text'])
print('Worker attempts:', job['attempt'])
PY
```

The default deterministic provider echoes the final message. The task should end in `succeeded` with `hello gateway`. IDs and timings vary. This walkthrough verifies the stack's happy path and idempotency behavior; it does not exercise recovery after a crash.

## Investigate a queued job

```bash
docker compose logs --tail=100 dispatcher worker
docker compose exec -T postgres psql -U gateway -d gateway -c \
  "SELECT status, count(*) FROM jobs GROUP BY status;"
docker compose exec -T postgres psql -U gateway -d gateway -c \
  "SELECT count(*) AS unpublished FROM outbox_events WHERE published_at IS NULL;"
```

An unpublished outbox row points to the dispatcher or broker. A published row with a queued job points to workers or delivery. An expired running lease points to worker failure or a provider call exceeding the lease. Use the [operations guide](operations.md) before replaying a message.
