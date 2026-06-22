# Plan: 007 — Postgres Job Queue

**Feature**: `007-postgres-job-queue`
**Date**: 2026-06-22

---

## Tech Stack

- **Language**: Python 3.12 — `from __future__ import annotations` in every module
- **DB access**: SQLAlchemy 2 asyncpg (already in `openkb/db.py`) — `text()` for raw SQL
- **Queue pattern**: `DELETE FROM compiler_jobs WHERE id = (SELECT id ... FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`
- **Config**: dataclass `WorkerConfig` (existing) — add `queue_backend: str`
- **Migration**: Alembic (`openkb/db/migrations/versions/`)
- **Testing**: existing `pytest` + `scripts/test_ingest.sh`

---

## File Structure

```text
openkb/db/migrations/versions/
└── 0002_add_compiler_jobs_queue.py    NEW — creates compiler_jobs table + index

compiler_worker/
├── queue_client.py                    MODIFY — add PostgresQueueClient; select via factory
├── config.py                          MODIFY — add queue_backend field; make REDIS_URL optional
└── worker.py                          MODIFY — use queue factory; update poll loop

openkb/db.py                           MODIFY — expose compiler_jobs table metadata (optional)

docker-compose.yml                     MODIFY — remove redis service + REDIS_URL env refs
scripts/test_ingest.sh                 MODIFY — replace LPUSH with INSERT INTO compiler_jobs
specs/007-postgres-job-queue/          NEW — spec, plan, tasks
```

---

## Architecture

```
test_ingest.sh / API
      │
      │  INSERT INTO compiler_jobs (kb_id, document_id, blob_path, filename)
      ▼
  [compiler_jobs table]  ← Postgres
      │
      │  DELETE ... FOR UPDATE SKIP LOCKED LIMIT 1 RETURNING *
      ▼
  PostgresQueueClient.dequeue()
      │
      ▼
  WorkerLoop._async_run()  →  process_job()  →  documents.status updated
```

---

## Key Design Decisions

1. **DELETE not UPDATE**: Jobs are deleted from `compiler_jobs` on claim rather than updated
   to `claimed`. The `documents.status='compiling'` column is the in-flight marker — this
   keeps the queue table lean and avoids a second UPDATE.

2. **Poll not notify**: `PostgresQueueClient` uses a sleep-poll loop (same as BRPOP timeout
   pattern) rather than `LISTEN/NOTIFY`. This keeps the implementation simple and avoids
   a persistent connection requirement.

3. **`QUEUE_BACKEND` env var**: Default `postgres`. Setting `QUEUE_BACKEND=redis` re-enables
   `RedisQueueClient` for teams already running Redis who want opt-in backwards compatibility.
   `RedisQueueClient` is not deleted.

4. **Stale recovery**: `compiler_jobs` rows with `status='pending'` that were enqueued before
   a worker crash are naturally re-claimable because the DELETE is atomic — if the worker
   crashes mid-job, the document is in `compiling` state but no job row exists. The existing
   `_recover_stale()` handles this by resetting those document rows to `failed`.

5. **`openkb/db.py` table metadata**: Add `compiler_jobs` to the existing SQLAlchemy `metadata`
   so the Alembic migration and any future ORM usage stays consistent.

---

## Environment Variable Changes

| Variable | Before | After |
|----------|--------|-------|
| `REDIS_URL` | Required | Optional (only needed if `QUEUE_BACKEND=redis`) |
| `QUEUE_BACKEND` | n/a | New, default `postgres` |

---

## Rollback Plan

Set `QUEUE_BACKEND=redis` and restore the `redis` service in `docker-compose.yml`.
No schema rollback needed (additive migration only).
