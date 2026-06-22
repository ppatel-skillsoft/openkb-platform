# Tasks: 007 — Postgres Job Queue

**Feature**: `007-postgres-job-queue` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Generated**: 2026-06-22

---

## Summary

- **Total tasks**: 10
- **User stories**: US1 (4 tasks), US2 (3 tasks), US3 (1 task)
- **Parallel opportunities**: T003/T004 in Phase 2
- **MVP scope**: Phase 1 + Phase 2 + Phase 3 (Redis fully decommissioned, Postgres queue live)

---

## Phase 1 — Migration

> Add the `compiler_jobs` table to Postgres. No code changes yet.

- [x] T001 [US1] Create Alembic migration `openkb/db/migrations/versions/0002_add_compiler_jobs_queue.py`: `CREATE TABLE compiler_jobs (id UUID PK DEFAULT gen_random_uuid(), kb_id UUID NOT NULL REFERENCES knowledge_bases(id), document_id UUID NOT NULL REFERENCES documents(id), blob_path TEXT NOT NULL, filename TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', enqueued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), claimed_at TIMESTAMPTZ, worker_id TEXT)`; add `CREATE INDEX ix_compiler_jobs_status ON compiler_jobs(status)`; `downgrade()` drops the table

---

## Phase 2 — Queue Client & Config

> Add `PostgresQueueClient` and wire backend selection. Parallel with T004.

- [x] T002 [US1] Add `compiler_jobs` table metadata to `openkb/db.py`: `sa.Table("compiler_jobs", metadata, sa.Column("id", UUID, ...), ...)` so the table is accessible via SQLAlchemy core from `queue_client.py`

- [x] T003 [P] [US1] Add `PostgresQueueClient` to `compiler_worker/queue_client.py`: async-compatible class with `dequeue(timeout: int) -> str | None` method; uses `asyncio.sleep`-based poll loop executing `DELETE FROM compiler_jobs WHERE id = (SELECT id FROM compiler_jobs WHERE status='pending' ORDER BY enqueued_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`; returns job as JSON string matching existing `CompilationJob` field names (`job_id=id`, `kb_id`, `document_id`, `blob_path`, `filename`, `enqueued_at`); accepts `database_url: str` and `poll_interval: float` in constructor; note: `dequeue()` must be called from an async context (unlike `RedisQueueClient` which is sync/threaded)

- [x] T004 [P] [US2] Update `compiler_worker/config.py`: add `queue_backend: str = "postgres"` field; make `REDIS_URL` optional (remove from `_REQUIRED` list, default to `""`); add `QUEUE_BACKEND` env var reading (default `"postgres"`)

---

## Phase 3 — Worker Integration

> Swap the worker loop to use the selected queue client.

- [x] T005 [US1] Update `compiler_worker/worker.py`: replace hardcoded `RedisQueueClient` instantiation with a factory — `if config.queue_backend == "redis": queue = RedisQueueClient(...) else: queue = PostgresQueueClient(...)`; update `_async_run()` to call `await queue.dequeue(...)` for `PostgresQueueClient` (async) vs `loop.run_in_executor(None, queue.dequeue, ...)` for `RedisQueueClient` (sync/blocking); keep both paths working

---

## Phase 4 — Docker Compose Decommission

> Remove Redis from the stack entirely.

- [x] T006 [US2] Update `docker-compose.yml`: remove the `redis` service block; remove `REDIS_URL` from `compiler-worker` environment; remove `redis` from `compiler-worker` `depends_on`; remove Redis from the top-level comment

- [x] T007 [US2] Update `.env` and `.env.azure.example`: remove or comment out `REDIS_URL`; add `QUEUE_BACKEND=postgres` with comment explaining `redis` opt-in

---

## Phase 5 — Script & Stale Recovery

> Update test script and ensure stale recovery handles the new queue.

- [x] T008 [US3] Update `scripts/test_ingest.sh`: replace `docker compose exec redis redis-cli LPUSH compiler:jobs '{...}'` with `docker compose exec -T postgres psql -U openkb -d openkb -c "INSERT INTO compiler_jobs (kb_id, document_id, blob_path, filename) VALUES ('${KB_ID}', '${DOC_ID}', '${BLOB_PATH}', '${FILENAME}') RETURNING id"`; verify job is picked up by the worker within the existing 30s wait loop

---

## Phase 6 — Migration Apply & Smoke Test

> Run the migration, rebuild, and verify end-to-end.

- [x] T009 Run `docker compose exec compiler-worker alembic upgrade head` (or equivalent) to apply migration `0002`; verify `compiler_jobs` table exists in Postgres

- [x] T010 Run `./scripts/test_ingest.sh` end-to-end and confirm: (1) job row inserted into `compiler_jobs`; (2) worker claims and deletes the job row; (3) document status reaches `complete`; (4) no Redis errors in any service logs

---

## Dependencies

```
T001 → T002 → T003
T001 → T004
T003 → T005
T004 → T005
T005 → T006
T005 → T007
T005 → T008
T006 → T009
T008 → T009
T009 → T010
```

---

## Parallel Execution

**Phase 2** (once T001 + T002 done):
```
T003  PostgresQueueClient   ──┐
T004  config.py update     ──┴─→ T005 worker.py
```
