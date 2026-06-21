# Contract: Job Queue Message

**Feature**: `003-compiler-worker-skeleton`  
**Date**: 2026-06-21  
**Queue backend**: Redis list (`LPUSH` to enqueue, `BRPOP` to consume)  
**Queue key**: `compiler:jobs` (configurable via `QUEUE_KEY` env var)

---

## Overview

The compiler-worker consumes JSON messages from a Redis list. Each message
represents one compilation job: a single document to compile within a single
knowledge base.

---

## Message Schema

### Enqueue (producer writes)

```json
{
  "job_id":      "550e8400-e29b-41d4-a716-446655440000",
  "kb_id":       "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "document_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "blob_path":   "kb-a1b2c3d4-e5f6-7890-abcd-ef1234567890/raw/report.md",
  "filename":    "report.md",
  "enqueued_at": "2026-06-21T15:35:00Z"
}
```

### Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `job_id` | string (UUID v4) | ✅ | Idempotency key; logged throughout job processing |
| `kb_id` | string (UUID v4) | ✅ | FK → `knowledge_bases.id`; worker looks up KB config |
| `document_id` | string (UUID v4) | ✅ | FK → `documents.id`; worker updates this row's status |
| `blob_path` | string | ✅ | Full blob path of the source document (container + blob name). Example: `kb-{kb_id}/raw/report.md` |
| `filename` | string | ✅ | Original filename; used as the destination filename under `raw/` in the scratch directory |
| `enqueued_at` | string (ISO-8601 UTC) | ✅ | Timestamp when the job was placed on the queue; used for observability logging only |

---

## Enqueue Command (producer)

```bash
# Using redis-cli (local dev / manual testing)
redis-cli LPUSH compiler:jobs \
  '{"job_id":"550e8400-e29b-41d4-a716-446655440000","kb_id":"a1b2c3d4-e5f6-7890-abcd-ef1234567890","document_id":"f47ac10b-58cc-4372-a567-0e02b2c3d479","blob_path":"kb-a1b2c3d4-e5f6-7890-abcd-ef1234567890/raw/report.md","filename":"report.md","enqueued_at":"2026-06-21T15:35:00Z"}'
```

```python
# Using redis-py (programmatic producer — e.g. a seed script)
import json, redis, uuid
from datetime import datetime, timezone

r = redis.from_url("redis://localhost:6379/0")
r.lpush("compiler:jobs", json.dumps({
    "job_id":      str(uuid.uuid4()),
    "kb_id":       KB_ID,
    "document_id": DOCUMENT_ID,
    "blob_path":   f"kb-{KB_ID}/raw/report.md",
    "filename":    "report.md",
    "enqueued_at": datetime.now(timezone.utc).isoformat(),
}))
```

---

## Dequeue Pattern (worker)

```python
# Blocks up to QUEUE_POLL_TIMEOUT_S seconds; returns None on timeout
result = r.brpop(QUEUE_KEY, timeout=QUEUE_POLL_TIMEOUT_S)
if result is None:
    continue  # poll again
_, raw = result
job = CompilationJob(**json.loads(raw))
```

---

## Error Handling

| Condition | Worker behaviour |
|---|---|
| Malformed JSON | Log error with raw message; discard (do not crash) |
| Missing required field | Log error; discard |
| `document_id` not found in Postgres | Set document `failed` (if found) or log and discard |
| `kb_id` not found in Postgres | Log and discard; no document row to update |

---

## Production Swap (Azure Service Bus)

For production, replace `RedisQueueClient` with `AzureServiceBusQueueClient`
(out of scope for Phase 0). The message schema is identical; only the
transport changes. Set `QUEUE_BACKEND=azservicebus` to activate the
production client (the `QueueClient` protocol remains the same).

---

## Constraints

- Messages are consumed FIFO (Redis list, right-pop / left-push).
- No dead-letter queue in Phase 0; malformed messages are discarded.
- No retry on processing failure; the document row is set to `failed` and
  the job is complete.
- Maximum message size is well within Redis's 512 MB string limit (~250 bytes
  per message).
