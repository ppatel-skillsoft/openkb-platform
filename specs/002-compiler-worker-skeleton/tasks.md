# Tasks: Compiler Worker Skeleton (Phase 0)

**Feature**: `003-compiler-worker-skeleton`  
**Branch**: `003-compiler-worker-skeleton`  
**Input**: `specs/002-compiler-worker-skeleton/` — plan.md, spec.md, data-model.md, research.md, contracts/

## Format: `[ID] [P?] [Story?] Description — file path`

- **[P]**: Parallelizable with other [P] tasks in the same phase
- **[US1/US2/US3]**: Which user story this task delivers
- Exact file paths included in every description

---

## Phase 1: Setup

**Purpose**: Add new runtime dependencies and create the package skeleton so later phases can import without stubs.

- [X] T001 Add `redis>=5.0.0`, `httpx>=0.27.0`, `aiofiles>=23.0.0` to `[project.dependencies]` in `pyproject.toml` and run `uv lock` to update `uv.lock`
- [X] T002 Create `compiler_worker/` package skeleton — `compiler_worker/__init__.py` (empty), `compiler_worker/__main__.py` (placeholder `print("not yet implemented")`), and `tests/unit/compiler_worker/__init__.py`, `tests/integration/compiler_worker/__init__.py` (both empty)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data structures, config, and infrastructure clients that every user-story phase depends on. No user-story work begins until these are done.

**⚠️ CRITICAL**: All US1, US2, US3 tasks depend on this phase being complete.

- [X] T003 Create `compiler_worker/config.py` — `WorkerConfig` dataclass with `from_env()` classmethod; required vars: `DATABASE_URL`, `REDIS_URL`, `AZURE_STORAGE_CONNECTION_STRING`, `SIDECAR_CMD`, `KB_ID`; optional with defaults: `QUEUE_KEY`, `QUEUE_POLL_TIMEOUT_S`, `SIDECAR_STARTUP_TIMEOUT_S`, `SIDECAR_COMPILE_TIMEOUT_S`, `SIDECAR_POLL_INTERVAL_S`, `LOG_LEVEL`; raises `ValueError` immediately on any missing required var; calls `load_dotenv()` before reading env; exact field names per `contracts/env-config.md`
- [X] T004 [P] Create `compiler_worker/models.py` — `CompilationJob`, `SidecarPage`, `SidecarStatus` dataclasses exactly as specified in `specs/002-compiler-worker-skeleton/data-model.md` §2 (In-Memory Models); add `from __future__ import annotations`; no Pydantic — plain `@dataclass` only
- [X] T005 [P] Verify `openkb/db/__init__.py` re-exports `get_session` (async session factory), `engine`, and SQLAlchemy table objects (`knowledge_bases`, `documents`, `wiki_pages`); if `openkb/db/session.py` is missing, create it with `async_sessionmaker` over `asyncpg` using `DATABASE_URL`; confirm `documents` and `wiki_pages` tables have all columns written by the worker per `specs/002-compiler-worker-skeleton/data-model.md` §1
- [X] T006 [P] Create `compiler_worker/queue_client.py` — `QueueClient` `Protocol` with `dequeue(timeout: int) -> str | None`; `RedisQueueClient` concrete class using `redis.from_url(config.redis_url)` and `BRPOP(config.queue_key, timeout=config.queue_poll_timeout)`; returns raw JSON string or `None` on timeout; `parse_job(raw: str) -> CompilationJob` helper that logs-and-discards on `json.JSONDecodeError` or missing fields (never crashes); per `contracts/job-queue-message.md`
- [X] T007 [P] Create `compiler_worker/blob_client.py` — `BlobStorageClient` wrapping `azure.storage.blob.BlobServiceClient`; `download_to_file(blob_path: str, dest: Path) -> None` splits container from blob name on first `/`; `upload_from_file(blob_path: str, src: Path) -> None`; `ensure_container(container: str) -> None` creates container if absent; raises `ResourceNotFoundError` transparently; per `contracts/blob-storage-paths.md` path conventions (`kb-{id}/raw/{filename}`, `kb-{id}/wiki/{slug}.md`)

**Checkpoint**: Config, models, DB layer, queue client, blob client all importable — US1 implementation can now begin.

---

## Phase 3: User Story 1 — Document Compiles End-to-End (Priority: P1) 🎯 MVP

**Goal**: Worker dequeues a job, drives sidecar through `init → add → status`, uploads wiki pages to Blob Storage, persists results in Postgres — full end-to-end compilation succeeds.

**Independent Test**: Upload a `.md` blob to Azurite, insert `knowledge_bases` + `documents` rows, push a job onto `compiler:jobs`, run `process_job()` — verify `documents.status = 'complete'` with non-null `token_cost` and `pageindex_used`, `wiki_pages` rows present, and wiki blobs in Azurite under `kb-{id}/wiki/`.

- [X] T008 [US1] Create `compiler_worker/sidecar.py` — `SidecarProcess` class: `allocate_port()` via `socket.bind(('', 0))` + immediate release; `start(config, scratch_dir)` calls `subprocess.Popen([*shlex.split(config.sidecar_cmd), '--host', '127.0.0.1', '--port', str(port)], cwd=scratch_dir)`; health poll: `GET /health` up to 30 × 0.5 s via `httpx`; `init(model, language)` → `POST /init`; `add(filename)` → `POST /add`; `get_status()` → `GET /status` returns `SidecarStatus`; `teardown()` sends `SIGTERM`, waits 5 s, `SIGKILL` if alive; raises `SidecarStartError` on health timeout; all HTTP calls raise on non-2xx; per `contracts/sidecar-http-api.md`
- [X] T009 [US1] Create `compiler_worker/job.py` — `process_job(job: CompilationJob, config: WorkerConfig, db_session, blob_client: BlobStorageClient) -> None`; steps: (1) look up `knowledge_bases` row — raise `KBNotFoundError` if absent; (2) create `tempfile.mkdtemp(prefix='openkb-job-')`, `(scratch / 'raw').mkdir()`; (3) `blob_client.download_to_file(job.blob_path, scratch / 'raw' / job.filename)` — catch `ResourceNotFoundError`, set doc `failed`, return; (4) update `documents.status = 'compiling'`; (5) `try: sidecar.start(); sidecar.init(); sidecar.add(job.filename); poll sidecar.get_status() until complete/failed/timeout; upload each page blob; upsert wiki_pages rows; update documents to complete; finally: sidecar.teardown(); shutil.rmtree(scratch, ignore_errors=True)`; all SQL per `specs/002-compiler-worker-skeleton/data-model.md` §1 write patterns
- [X] T010 [US1] Create `compiler_worker/worker.py` — `WorkerLoop(config: WorkerConfig)`; `run()`: configure logging, open async DB session factory, startup stale recovery (described fully in T019), enter `while not self._shutdown:` loop calling `queue_client.dequeue()`, deserialise via `parse_job()`, call `asyncio.run(process_job(...))`, catch and log all `Exception` without crashing loop; `SIGTERM`/`SIGINT` handler sets `self._shutdown = True`; idle poll cycles log at DEBUG level; per FR-001, FR-013, R-009
- [X] T011 [US1] Create `compiler_worker/__main__.py` — `main()`: call `load_dotenv()`, `WorkerConfig.from_env()`, configure root logger at `config.log_level`, instantiate and run `WorkerLoop`; `if __name__ == '__main__': main()` — satisfies FR-014 (`python -m compiler_worker`)
- [X] T012 [P] [US1] Write `tests/unit/compiler_worker/test_sidecar.py` — unit tests: `allocate_port()` returns an integer in valid port range; `start()` with mocked `Popen` and `httpx` client succeeds when `/health` returns 200; `start()` raises `SidecarStartError` when health poll never returns 200 within 30 retries; `teardown()` sends `SIGTERM` then `SIGKILL` when process doesn't exit; `get_status()` deserialises all four `status` variants (`idle`, `compiling`, `complete`, `failed`)
- [X] T013 [P] [US1] Write `tests/unit/compiler_worker/test_queue.py` — unit tests: `RedisQueueClient.dequeue()` returns JSON string when BRPOP returns a value; returns `None` on timeout; `parse_job()` returns `CompilationJob` for valid JSON; logs and returns `None` for malformed JSON; logs and returns `None` for valid JSON missing required fields; all using `unittest.mock` to mock `redis.Redis`
- [X] T014 [P] [US1] Write `tests/unit/compiler_worker/test_blob.py` — unit tests: `download_to_file()` splits `kb-{id}/raw/file.md` into container `kb-{id}` and blob `raw/file.md`; `upload_from_file()` constructs correct container + blob name; `ensure_container()` calls `create_container` if absent; all using `unittest.mock` to mock `BlobServiceClient`
- [X] T015 [US1] Write `tests/integration/compiler_worker/conftest.py` — pytest fixtures: `async_db_session` using real asyncpg + `DATABASE_URL` from env; `blob_client` pointing at Azurite `AZURE_STORAGE_CONNECTION_STRING`; `redis_client` from `REDIS_URL`; `worker_config` loaded from env; `seed_kb` fixture inserts a `knowledge_bases` row and cleans up after; `seed_document` fixture inserts a `documents` row with status `pending`; mark all integration tests with `@pytest.mark.integration`
- [X] T016 [US1] Write `tests/integration/compiler_worker/test_job_lifecycle.py` — happy-path end-to-end test: upload a real `.md` test fixture to Azurite `raw/` path; insert `knowledge_bases` + `documents` rows; mock sidecar HTTP calls to return `complete` with 2 pages; call `process_job()`; assert `documents.status == 'complete'`, `token_cost` is not None, `pageindex_used` is not None; assert 2 `wiki_pages` rows with correct `slug`, `blob_path`, `page_type`; assert 2 blobs exist in Azurite under `kb-{id}/wiki/`; assert scratch directory no longer exists after job

---

## Phase 4: User Story 2 — Failed Compilation Is Recorded Cleanly (Priority: P2)

**Goal**: Every failure mode (sidecar error, timeout, missing blob, missing KB) transitions `documents` to `failed` with a human-readable `failure_reason`, sidecar is torn down, and the worker continues processing the next job.

**Independent Test**: Enqueue a job referencing a document that causes the sidecar to return an error status; verify `documents.status = 'failed'` with non-empty `failure_reason`, no `wiki_pages` rows written, and the worker processes a subsequent valid job successfully. Also verify stale `compiling` recovery on worker startup.

- [X] T017 [US2] Add `SidecarCompileError(reason: str)`, `SidecarTimeoutError(timeout_s: int)`, `SidecarStartError`, `KBNotFoundError`, `BlobNotFoundError` custom exceptions to `compiler_worker/exceptions.py`; import them in `compiler_worker/sidecar.py` and `compiler_worker/job.py`; `SidecarProcess.get_status()` raises `SidecarCompileError` when `status.status == 'failed'`; polling loop in `job.py` raises `SidecarTimeoutError` when `time.monotonic() > deadline`; per FR-016, FR-017
- [X] T018 [US2] Extend `compiler_worker/job.py` failure branches: catch `BlobNotFoundError` after download → set doc `failed`, `failure_reason='Source blob not found in storage'`, skip sidecar; catch `KBNotFoundError` → set doc `failed`, `failure_reason='knowledge_bases row not found for kb_id: {id}'`; catch `SidecarCompileError` → set doc `failed`, `failure_reason=error.reason`; catch `SidecarTimeoutError` → set doc `failed`, `failure_reason=f'Compilation timed out after {n}s'`; catch generic `Exception` → set doc `failed`, `failure_reason=repr(e)`; log R-008 limitation comment if blob upload succeeded before Postgres failure; all per FR-010, FR-016, FR-017, R-007, R-008
- [X] T019 [US2] Add stale-compiling recovery to `compiler_worker/worker.py` `run()` startup: query `documents WHERE status = 'compiling' AND deleted_at IS NULL`; bulk `UPDATE documents SET status = 'failed', failure_reason = 'Worker restarted with job in progress — marked failed for safety', updated_at = now()`; log count of resolved documents at INFO level; per FR-018, R-005, `data-model.md` §1 stale recovery SQL pattern
- [X] T020 [P] [US2] Write `tests/unit/compiler_worker/test_config.py` — unit tests: `WorkerConfig.from_env()` succeeds with all required vars set; raises `ValueError` naming missing vars when any required var is absent; optional vars fall back to documented defaults (`QUEUE_KEY='compiler:jobs'`, `QUEUE_POLL_TIMEOUT_S=5`, etc.); uses `monkeypatch.setenv` / `monkeypatch.delenv`
- [X] T021 [US2] Write `tests/integration/compiler_worker/test_failure_recording.py` — tests: (1) mock sidecar `/add` → 404 → assert `documents.failed` with non-empty `failure_reason`, no `wiki_pages` rows; (2) mock sidecar `/status` to never return `complete` within `sidecar_compile_timeout=2` → assert `documents.failed` with timeout reason; (3) call `process_job()` with non-existent blob path → assert `documents.failed` with blob-not-found reason; (4) call `process_job()` with unknown `kb_id` → assert document remains `pending` or `failed` with KB-not-found reason; (5) after any failure, enqueue a valid second job and confirm it completes successfully
- [X] T022 [US2] Write `tests/integration/compiler_worker/test_stale_recovery.py` — insert 3 `documents` rows with `status = 'compiling'`; instantiate `WorkerLoop` and call the startup-recovery method directly; assert all 3 rows now have `status = 'failed'` and non-empty `failure_reason`; assert a 4th row with `status = 'pending'` is untouched; assert worker log reports "3 stale documents resolved"

---

## Phase 5: User Story 3 — Local Dev Stack Runs via Docker Compose (Priority: P3)

**Goal**: `docker compose up --build` starts all five services (Postgres, Azurite, Redis, sidecar, compiler-worker), all reach healthy state, and an end-to-end compilation job completes without manual configuration.

**Independent Test**: Run `docker compose up` from a clean checkout; confirm all five service health checks pass; manually enqueue a job via `redis-cli` and verify end-to-end compilation per `quickstart.md` steps 3–7.

- [X] T023 [US3] Create `Dockerfile.compiler-worker` — multi-stage: stage 1 (`builder`) uses `python:3.12-slim`, installs `uv`, copies `pyproject.toml` + `uv.lock`, runs `uv sync --no-dev`; stage 2 (`runtime`) copies virtual env and source (`openkb/`, `compiler_worker/`); sets `WORKDIR /app`, `CMD ["python", "-m", "compiler_worker"]`; does not include sidecar source (sidecar is a separate service)
- [X] T024 [US3] Update `docker-compose.yml` — add `compiler-worker` service using `Dockerfile.compiler-worker`, depends_on `postgres`, `azurite`, `redis` all healthy; set all env vars per `contracts/env-config.md` Docker Compose defaults (`DATABASE_URL`, `REDIS_URL`, `AZURE_STORAGE_CONNECTION_STRING`, `SIDECAR_CMD`, `KB_ID`, `LOG_LEVEL`); verify existing `sidecar` service definition is present and correct; add `healthcheck` blocks to all five services; Postgres uses `pg_isready`, Azurite uses `curl -f http://azurite:10000/`, Redis uses `redis-cli ping`, sidecar uses `curl -f http://localhost:8000/health`, worker uses process-alive check
- [X] T025 [P] [US3] Update `.env.example` — add all `WorkerConfig` env vars (`DATABASE_URL`, `REDIS_URL`, `AZURE_STORAGE_CONNECTION_STRING`, `SIDECAR_CMD`, `KB_ID`, `QUEUE_KEY`, `QUEUE_POLL_TIMEOUT_S`, `SIDECAR_STARTUP_TIMEOUT_S`, `SIDECAR_COMPILE_TIMEOUT_S`, `SIDECAR_POLL_INTERVAL_S`, `LOG_LEVEL`) with example values from `contracts/env-config.md` §Standalone Debug; add comment block separating existing `openkb` vars from new `compiler_worker` vars

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T026 [P] Update `pyproject.toml` `[project]` to ensure `compiler_worker` package is discovered alongside `openkb`; verify `pytest` test discovery config in `[tool.pytest.ini_options]` covers `tests/unit/compiler_worker/` and `tests/integration/compiler_worker/`; add `asyncio_mode = "auto"` if not already present
- [X] T027 [P] Smoke-test `python -m compiler_worker` standalone entry point: with all required env vars set but Redis unavailable, confirm it exits with a clear `ValueError` (missing env vars) rather than a connection traceback; with all vars set and Redis reachable, confirm it logs "Worker started — polling compiler:jobs" and idles cleanly

---

## Dependencies

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6
                     US1 T008–T016
                                        US2 T017–T022
                                                        US3 T023–T025
```

US3 (Docker Compose) is independent of US1/US2 _code_ — it wraps the final binaries. Can start T023–T025 once Phase 2 is done.

| Story | Depends on |
|---|---|
| US1 (T008–T016) | Phase 2 complete (T003–T007) |
| US2 (T017–T022) | US1 core logic (T008–T011) |
| US3 (T023–T025) | Phase 2 complete (T003–T007); T023 needs T011 for `__main__` entry point |
| Phase 6 (T026–T027) | US1 + US2 + US3 complete |

---

## Parallel Execution Examples

**Within Phase 2** (after T003): T004, T005, T006, T007 can all run simultaneously.

**Within Phase 3** (after T008+T009 complete): T012, T013, T014 can run in parallel; T015 must precede T016.

**Within Phase 4** (after T017+T018+T019): T020, T021, T022 can run in parallel with each other.

**Within Phase 5**: T023 and T024 can run in parallel; T025 is independent of both.

---

## Implementation Strategy

**MVP scope** = Phase 1 + Phase 2 + Phase 3 (T001–T016).  
US1 alone demonstrates the full compilation pipeline and satisfies SC-001, SC-002, SC-003, SC-006.

Add US2 (T017–T022) immediately after — failure handling is required for reliability before Docker Compose integration.

US3 (T023–T025) wraps the completed worker into the five-service stack per SC-004.

---

## Summary

| Phase | Tasks | User Story | Key Deliverable |
|---|---|---|---|
| Setup | T001–T002 | — | Dependencies + package skeleton |
| Foundational | T003–T007 | — | Config, models, DB, queue, blob clients |
| Phase 3 | T008–T016 | US1 (P1) | Full end-to-end happy-path compilation |
| Phase 4 | T017–T022 | US2 (P2) | Failure recording + stale recovery |
| Phase 5 | T023–T025 | US3 (P3) | Docker Compose five-service stack |
| Polish | T026–T027 | — | Package discovery + entry-point smoke test |

**Total tasks**: 27  
**Parallelizable**: T004, T005, T006, T007, T012, T013, T014, T020, T025, T026, T027 (11 tasks)  
**MVP**: T001–T016 (16 tasks — US1 complete)
