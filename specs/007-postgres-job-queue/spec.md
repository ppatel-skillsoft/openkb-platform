# Spec 007 — Postgres Job Queue (Redis Decommission)

**Feature branch**: `007-postgres-job-queue`
**Status**: Draft
**Author**: OpenKB team
**Date**: 2026-06-22

---

## Problem

The compiler-worker currently uses Redis as its job queue (LPUSH/BRPOP pattern). Redis is an
additional infrastructure dependency that adds cost and operational complexity for self-hosted
deployments. The only Redis feature used is a simple FIFO queue — there is no caching, pub/sub,
or session storage.

PostgreSQL is already a required dependency and supports a proven job queue pattern via
`SELECT ... FOR UPDATE SKIP LOCKED`, which provides the same at-most-once delivery guarantee
as Redis BRPOP with no additional infrastructure.

---

## Goal

Replace Redis with a Postgres-backed `compiler_jobs` table so the stack runs with one fewer
service. Redis is fully decommissioned from `docker-compose.yml` and all configuration.

---

## User Stories

### US1 — Jobs enqueued and consumed via Postgres

**As a** developer running the stack locally,
**I want** compilation jobs to be stored in a `compiler_jobs` Postgres table,
**So that** I do not need Redis running to process documents.

**Acceptance criteria**:
- `POST /ingest` (or `scripts/test_ingest.sh`) enqueues a job row in `compiler_jobs`
- Compiler-worker claims and processes the job using `SELECT ... FOR UPDATE SKIP LOCKED`
- Document status transitions: `pending → compiling → complete/failed` as before
- No Redis process required in the Docker Compose stack

### US2 — Redis fully removed from the stack

**As a** self-hosted operator,
**I want** Redis removed from `docker-compose.yml` and all configuration files,
**So that** the stack is simpler and cheaper to run.

**Acceptance criteria**:
- `docker compose up` succeeds without a `redis` service
- `REDIS_URL` env var is no longer required or referenced
- `compiler_worker/queue_client.py` retains `RedisQueueClient` behind a feature flag
  (`QUEUE_BACKEND=redis`) for opt-in backwards compatibility, but default is `postgres`

### US3 — Stale job recovery on worker restart

**As a** developer,
**I want** jobs claimed but not completed (worker crash) to be automatically re-queued,
**So that** no documents are permanently stuck.

**Acceptance criteria**:
- On worker startup, any `compiler_jobs` row with `status='claimed'` older than
  `STALE_JOB_TIMEOUT_S` (default 600s) is reset to `status='pending'`
- Existing `_recover_stale()` in `worker.py` continues to reset `documents.status='compiling'`
  rows to `failed` in parallel with the job row recovery

---

## Out of Scope

- Redis as a cache, session store, or pub/sub — not currently used
- Distributed multi-worker coordination beyond `SKIP LOCKED`
- Job retry counts / exponential backoff (future spec)
- Removing `RedisQueueClient` class entirely (kept for opt-in compatibility)

---

## Technical Approach

### New `compiler_jobs` table

```sql
CREATE TABLE compiler_jobs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id       UUID NOT NULL REFERENCES knowledge_bases(id),
    document_id UUID NOT NULL REFERENCES documents(id),
    blob_path   TEXT NOT NULL,
    filename    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    claimed_at  TIMESTAMPTZ,
    worker_id   TEXT
);
CREATE INDEX ix_compiler_jobs_status ON compiler_jobs(status);
```

### Enqueue (replaces LPUSH)

Jobs are inserted by the API layer (or `test_ingest.sh`) as a simple INSERT:

```sql
INSERT INTO compiler_jobs (kb_id, document_id, blob_path, filename)
VALUES ($1, $2, $3, $4);
```

### Dequeue (replaces BRPOP)

```sql
DELETE FROM compiler_jobs
WHERE id = (
    SELECT id FROM compiler_jobs
    WHERE status = 'pending'
    ORDER BY enqueued_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING *;
```

This is atomic: the row is deleted from the queue and returned to the worker in one statement,
giving the same at-most-once delivery as BRPOP. No explicit `claimed` state transition needed
for the job row itself — the document's `compiling` status is the in-flight marker.

### Worker poll loop

`PostgresQueueClient.dequeue(timeout)` runs the DELETE...RETURNING in a loop with `asyncio.sleep`
between polls (replacing the blocking BRPOP thread). The poll interval is controlled by
`QUEUE_POLL_TIMEOUT_S` (default 5s).

### Backend selection

`QUEUE_BACKEND=postgres` (default) → `PostgresQueueClient`
`QUEUE_BACKEND=redis` → `RedisQueueClient` (opt-in, requires `REDIS_URL`)

---

## Migration

Alembic migration `0002_add_compiler_jobs_queue.py`:
- Creates `compiler_jobs` table with index
- No destructive changes to existing tables
