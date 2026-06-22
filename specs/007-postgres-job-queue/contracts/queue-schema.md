# Contracts: Postgres Job Queue

## `compiler_jobs` Table Schema

```sql
CREATE TABLE compiler_jobs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id       UUID        NOT NULL REFERENCES knowledge_bases(id),
    document_id UUID        NOT NULL REFERENCES documents(id),
    blob_path   TEXT        NOT NULL,
    filename    TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending',
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at  TIMESTAMPTZ,
    worker_id   TEXT
);

CREATE INDEX ix_compiler_jobs_status ON compiler_jobs(status);
```

## Enqueue Contract (INSERT)

```sql
INSERT INTO compiler_jobs (kb_id, document_id, blob_path, filename)
VALUES ($1, $2, $3, $4)
RETURNING id;
```

Called by: `scripts/test_ingest.sh`, future API layer.

## Dequeue Contract (DELETE ... RETURNING)

```sql
DELETE FROM compiler_jobs
WHERE id = (
    SELECT id FROM compiler_jobs
    WHERE status = 'pending'
    ORDER BY enqueued_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, kb_id, document_id, blob_path, filename, enqueued_at;
```

Returns 0 rows if queue is empty (no block — poll loop handles waiting).

## Job JSON Wire Format

`PostgresQueueClient.dequeue()` returns the same JSON string shape as `RedisQueueClient`:

```json
{
  "job_id":      "<uuid>",
  "kb_id":       "<uuid>",
  "document_id": "<uuid>",
  "blob_path":   "kb-<id>/raw/hello.md",
  "filename":    "hello.md",
  "enqueued_at": "2026-06-22T10:00:00Z"
}
```

Note: `id` from the DB row is mapped to `job_id` for `CompilationJob` compatibility.

## Environment Variables

| Variable | Default | Required | Notes |
|----------|---------|----------|-------|
| `QUEUE_BACKEND` | `postgres` | No | Set to `redis` for opt-in Redis mode |
| `REDIS_URL` | `""` | No (only if `QUEUE_BACKEND=redis`) | Removed from required list |
| `DATABASE_URL` | — | Yes | Already required |
