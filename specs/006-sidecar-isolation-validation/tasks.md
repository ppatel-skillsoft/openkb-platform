# Tasks: 006 — Sidecar Isolation Validation Suite

**Feature**: `006-sidecar-isolation-validation` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Generated**: 2026-06-22

> **⚠️ Note — Queue Backend Change (spec 007)**:
> The original spec and `test-invocation.md` contract reference Redis (`REDIS_URL`, `LPUSH`).
> Redis has been replaced by a Postgres `compiler_jobs` table (spec 007, merged to develop).
> All tasks below use `INSERT INTO compiler_jobs` for job enqueue and have **no** Redis dependency.
> The `REDIS_URL` env var is **not required**. Replace with `QUEUE_BACKEND=postgres` (default).

---

## Summary

- **Total tasks**: 14
- **User stories**: US1 (1 task), US2 (1 task), US3 (1 task), US4 (1 task), US5 (1 task)
- **Parallel opportunities**: T004/T005 (helpers); T009–T013 (scenario tests after conftest)
- **MVP scope**: Phase 1 + Phase 2 + Phase 3 (US1 scratch isolation — most fundamental property)

---

## Phase 1 — Setup

> Scaffold the test package and add the `isolation-tests` extras.

- [X] T001 Create `tests/isolation/` directory structure: `__init__.py` at `tests/isolation/`, `tests/isolation/helpers/__init__.py`, and `tests/isolation/fixtures/kb_a/`, `tests/isolation/fixtures/kb_b/` directories (empty `__init__.py` files where needed)

- [X] T002 Add `isolation-tests` optional dependency group to `pyproject.toml`: `pytest==9.0.3`, `pytest-asyncio==1.3.0`, `asyncpg==0.29.0`, `httpx==0.28.1`, `azure-storage-blob==12.24.0`, `psutil==6.0.0` (use versions already pinned in project where available); run `uv sync --extra isolation-tests` to lock

---

## Phase 2 — Foundational

> Fixtures, helpers, conftest, Dockerfile, and Compose additions. All prerequisites for scenario tests.

- [X] T003 Create KB fixture source documents:
  - `tests/isolation/fixtures/kb_a/astronomy-intro.md` — astronomy content with topic keywords: `main sequence`, `red giant`, `Hertzsprung-Russell`, `planetary nebula`, `stellar` (content per `contracts/kb-fixture-schema.md`)
  - `tests/isolation/fixtures/kb_b/botany-intro.md` — botany content with topic keywords: `chloroplast`, `photosynthesis`, `stomata`, `xylem`, `phloem`, `Calvin cycle` (content per `contracts/kb-fixture-schema.md`); zero overlap with KB-A keywords

- [X] T004 [P] Create `tests/isolation/helpers/process_helpers.py`: `wait_for_http(url, timeout)` polls GET until 200 or raises `TimeoutError`; `assert_port_bound(port)` uses `psutil.net_connections()` to assert a LISTEN socket exists on given port; `assert_proc_dead(pid)` asserts `psutil.pid_exists(pid)` is False; `list_scratch_dirs(scratch_root)` returns all subdirectories of `scratch_root`; `get_listening_ports()` returns set of all ports with LISTEN state

- [X] T005 [P] Create `tests/isolation/helpers/blob_helpers.py`: `seed_wiki_blobs(connection_string, kb_id, kb_slug)` async function uploads the pre-compiled wiki blobs for a KB fixture to Azurite per `contracts/kb-fixture-schema.md` (summary.md + concept page); `list_kb_blobs(connection_string, kb_id)` returns list of blob paths under `kb-{kb_id}/`; `delete_kb_blobs(connection_string, kb_id)` removes all blobs for a KB (idempotent); uses `azure-storage-blob` async SDK

- [X] T006 Create `tests/isolation/Dockerfile`: `FROM python:3.12-slim`; install `uv`; `COPY pyproject.toml uv.lock ./`; `RUN uv sync --extra isolation-tests --no-dev --frozen`; `COPY tests/ ./tests/`; `COPY openkb/ ./openkb/`; `ENV PATH=/app/.venv/bin:$PATH`; default `CMD ["pytest", "tests/isolation/", "-v", "--tb=short"]`

- [X] T007 Create `tests/isolation/conftest.py`: session-scoped `kb_fixtures` fixture that:
  1. Reads env vars: `DATABASE_URL` (asyncpg), `AZURE_STORAGE_CONNECTION_STRING` (Azurite), `GENERATOR_API_BASE_URL`, `COMPILER_WORKER_SCRATCH_ROOT`; raises `pytest.UsageError` listing missing vars
  2. Asserts fixture invariants: keyword disjointness, path uniqueness, slug uniqueness (per `contracts/kb-fixture-schema.md`)
  3. Seeds Postgres: `INSERT ... ON CONFLICT DO NOTHING` for `knowledge_bases`, `documents`, `wiki_pages` rows for KB-A and KB-B (UUIDs per `contracts/kb-fixture-schema.md`)
  4. Seeds Azurite blobs via `blob_helpers.seed_wiki_blobs()` for both KBs
  5. **Enqueue helper** `enqueue_job(db_conn, kb_id, document_id, blob_path, filename)`: `INSERT INTO compiler_jobs (kb_id, document_id, blob_path, filename) VALUES (...)` — **no Redis; Postgres queue only**
  6. Yields fixture config dataclass
  7. Teardown: deletes `wiki_pages`, `documents`, `knowledge_bases` rows and all blobs for both KBs (idempotent)

- [X] T008 Update `docker-compose.yml`: add `isolation-tests` service under `profiles: ["test"]` with `depends_on: postgres (healthy), azurite (healthy), compiler-worker (started), generator-api (healthy)` — **no Redis dependency**; env vars: `DATABASE_URL` (postgres internal hostname), `AZURE_STORAGE_CONNECTION_STRING` (azurite internal hostname), `GENERATOR_API_BASE_URL=http://generator-api:8001`, `COMPILER_WORKER_SCRATCH_ROOT=/scratch`, `QUEUE_BACKEND=postgres`; `volumes: [compiler_scratch:/scratch:ro]`; `command: ["pytest", "tests/isolation/", "-v", "--tb=short"]`; add `compiler_scratch` named volume to `compiler-worker` service (`/scratch`) and to `volumes:` block; add `SCRATCH_DIR_ROOT=/scratch` to `compiler-worker` env

---

## Phase 3 — User Story 1: Scratch Directory Isolation

> **Independent test**: two concurrent compilation jobs never share or cross-read scratch dirs; dirs are cleaned up on completion.

- [X] T009 [US1] Create `tests/isolation/test_scratch_directory_isolation.py`:
  - `test_concurrent_scratch_dirs_are_unique`: enqueue two jobs (KB-A + KB-B) via `INSERT INTO compiler_jobs`; while both `compiling`, snapshot `list_scratch_dirs(scratch_root)`; assert paths are distinct and no path is a prefix of the other (FR-007)
  - `test_scratch_dir_contains_only_own_files`: after each job completes, assert the scratch dir that existed during the job contained no filenames from the other KB's fixture (FR-007)
  - `test_scratch_dir_cleaned_after_job`: after job reaches `complete`/`failed`, assert no scratch dir for that job remains under `scratch_root` (FR-008)

---

## Phase 4 — User Story 2: Port Isolation

> **Independent test**: concurrent sidecars bind different ports; HTTP traffic goes to the correct sidecar.

- [X] T010 [US2] Create `tests/isolation/test_port_isolation.py`:
  - `test_concurrent_sidecars_bind_different_ports`: trigger two concurrent compilation jobs; while both sidecars are alive, assert `get_listening_ports()` contains two distinct ports used by the sidecars (FR-009)
  - `test_http_to_kba_port_returns_kba_content`: query KB-A's generator-api endpoint; assert response `answer` contains only KB-A topic keywords, none from KB-B (FR-010)
  - `test_no_prior_sidecar_on_port_before_new_bind`: after first job's sidecar tears down, record its port; when a new job starts on same port (or any port), assert prior PID is dead via `assert_proc_dead()` before new sidecar's health check passes (FR-011)

---

## Phase 5 — User Story 3: Process State Isolation

> **Independent test**: KB-B sidecar after KB-A teardown has zero access to KB-A artefacts.

- [X] T011 [US3] Create `tests/isolation/test_process_state_isolation.py`:
  - `test_kbb_sidecar_has_no_kba_artefacts`: run KB-A job to completion, tear down; start KB-B job; assert KB-B's scratch dir contains no files with KB-A topic keywords (FR-012)
  - `test_kbb_query_returns_only_kbb_citations`: `POST /kbs/{KB_B_ID}/query` to generator-api; assert `answer` contains KB-B keywords and zero KB-A keywords (FR-013)

---

## Phase 6 — User Story 4: Sequential Reuse Safety

> **Independent test**: after KB-A completes, KB-B job sees no residual process or directory.

- [X] T012 [US4] Create `tests/isolation/test_sequential_reuse_safety.py`:
  - `test_prior_sidecar_dead_before_next_starts`: record KB-A sidecar PID and port; wait for KB-A completion and teardown; assert `assert_proc_dead(kba_pid)` before enqueuing KB-B job (FR-014)
  - `test_kba_scratch_dir_deleted_before_kbb_starts`: record KB-A scratch dir path; wait for KB-A cleanup; assert path does not exist; enqueue KB-B; assert KB-B scratch path is different from where KB-A's was (FR-015)

---

## Phase 7 — User Story 5: Concurrent Query Isolation

> **Independent test**: two simultaneous queries each see only their own KB's wiki tree and citations.

- [X] T013 [US5] Create `tests/isolation/test_concurrent_query_isolation.py`:
  - `test_concurrent_query_responses_are_isolated`: use `asyncio.gather` to issue `POST /kbs/{KB_A_ID}/query` and `POST /kbs/{KB_B_ID}/query` simultaneously; assert KB-A response contains only KB-A keywords; assert KB-B response contains only KB-B keywords; neither contains keywords from the other (FR-016)
  - `test_concurrent_wiki_checkouts_have_distinct_paths`: during concurrent query processing, snapshot `list_scratch_dirs(scratch_root)`; assert the two checkout paths share no common prefix beyond `scratch_root` itself (FR-017)
  - `test_no_residual_state_after_concurrent_queries`: after both queries complete and sidecars tear down, assert `list_scratch_dirs(scratch_root)` is empty (FR-017 teardown)

---

## Phase 8 — Polish

- [ ] T014 Run `docker compose --profile test run --rm isolation-tests` and confirm all 5 scenario files pass; update task checkboxes; confirm no Redis references remain in suite output or service logs

---

## Dependencies

```
T001 → T002 → T003
T001 → T004
T001 → T005
T002 → T006
T003 → T007
T004 → T007
T005 → T007
T006 → T007
T007 → T008
T008 → T009
T008 → T010
T008 → T011
T008 → T012
T008 → T013
T009 → T014
T010 → T014
T011 → T014
T012 → T014
T013 → T014
```

---

## Parallel Execution

**Phase 2** (once T001 done):
```
T004  process_helpers.py  ──┐
T005  blob_helpers.py     ──┴─→ T007 conftest.py → T008 docker-compose
T006  Dockerfile          ──┘
```

**Phase 3–7** (once T007+T008 done — all scenario tests are independent):
```
T009  scratch isolation  ─┐
T010  port isolation     ─┤
T011  process state      ─┼─→ T014 smoke run
T012  sequential reuse   ─┤
T013  concurrent query   ─┘
```
