# Tasks: Phase 0 Generator API Service

**Feature**: `004-generator-api` | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)
**Generated**: 2026-06-21

---

## Summary

- **Total tasks**: 16
- **User stories**: US1 (7 tasks), US2 (2 tasks), US3 (3 tasks), US4 (1 task)
- **Parallel opportunities**: T002/T003/T004 in Phase 2; T011 during Phase 3
- **MVP scope**: Phase 1 + Phase 2 + Phase 3 (US1 happy path end-to-end)

---

## Phase 1 — Setup

> Scaffold the new `generator_api` Python package so all subsequent tasks have a home.

- [ ] T001 Create `generator_api/` package: `__init__.py` with `__version__ = "0.1.0"` and docstring; no other content yet

---

## Phase 2 — Foundational

> Configuration, DB access, and request/response models. These are shared prereqs — all three can be implemented in parallel.

- [ ] T002 [P] Create `generator_api/config.py`: `pydantic-settings` `Settings` class with all env vars from `specs/003-generator-api/contracts/env-config.md` (`DATABASE_URL`, `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_KB_CONTAINER`, `LLM_API_KEY`, `SIDECAR_STARTUP_TIMEOUT`, `GENERATOR_REQUEST_TIMEOUT`, `SCRATCH_DIR_ROOT`, `GENERATOR_HOST`, `GENERATOR_PORT`); `lru_cache`-wrapped `get_settings()`

- [ ] T003 [P] Create `generator_api/models.py`: Pydantic v2 `QueryRequest` (`question: str` non-empty after strip max 8000 chars, `save: bool = False`); `QueryResponse` (`answer: str`, `citations: list[Any]`, `tokens_used: int`); `HealthResponse` (`status`, `postgres`, `azurite`, optional `detail`)

- [ ] T004 [P] Create `generator_api/db.py`: async SQLAlchemy engine created from `settings.database_url`; `get_db()` async generator yielding an `AsyncSession`; `check_postgres()` coroutine that runs `SELECT 1` and returns `"ok"` or `"error: {msg}"`

---

## Phase 3 — User Story 1: Developer Submits a Query and Gets a Grounded Answer

> Core happy-path query flow: blob sync → sidecar spawn → init → query → teardown.
> **Independent test**: `POST /kbs/{kb_id}/query` returns 200 with non-empty `answer` and `citations` list against a compiled KB.

- [ ] T005 [US1] Create `generator_api/blob.py`: `sync_wiki_tree(connection_string, container, kb_blob_prefix, scratch_dir)` async function — lists all blobs under `{kb_blob_prefix}/wiki/` using `azure-storage-blob` async SDK; downloads each to `{scratch_dir}/wiki/{relative_path}`; raises `BlobSyncError` (custom exception) if zero blobs found or any download fails; also add `check_azurite(connection_string)` coroutine that calls `list_containers()` and returns `"ok"` or `"error: {msg}"`

- [ ] T006 [US1] Create `generator_api/sidecar.py`: `SidecarProcess` class with `start(scratch_dir, kb_slug, settings)`, `init(kb_slug)`, `query(kb_slug, question)`, `teardown()` methods; `start()` allocates a free TCP port (`socket.bind(0)`), spawns `openkb serve --host 127.0.0.1 --port {port}` via `subprocess.Popen` with `cwd=scratch_dir`, env vars `OPENKB_STORAGE_BACKEND=local OPENKB_BASE_DIR={scratch_dir} OPENAI_API_KEY={settings.llm_api_key} AZURE_STORAGE_CONNECTION_STRING="" AZURE_KB_CONTAINER=""`; polls `GET /openapi.json` until 200 or `SIDECAR_STARTUP_TIMEOUT` exceeded (raise `SidecarStartError`); `query()` calls `POST /kb/query` with `{"kb_name": kb_slug, "question": question, "save": false}` and returns `(answer, citations, tokens_used)` from response; `teardown()` sends SIGTERM → waits 5s → SIGKILL; all methods sync-safe (called from async code via `asyncio.to_thread` where needed)

- [ ] T007 [US1] Create `generator_api/router.py`: `APIRouter`; `POST /kbs/{kb_id}/query` handler — (1) DB preflight: query `knowledge_bases` WHERE `id=kb_id AND deleted_at IS NULL` → 404 if missing; (2) DB preflight: `COUNT(*) FROM documents WHERE kb_id=kb_id AND status='complete' AND deleted_at IS NULL` → 409 if 0; (3) generate `request_id = uuid4()`; create `scratch_dir = settings.scratch_dir_root / str(request_id) / "kbs"`; (4) call `sync_wiki_tree()` with `kb_slug = kb.slug` as prefix; (5) spawn sidecar, call `sidecar.init(kb.slug)` then `sidecar.query(kb.slug, question)` wrapped in `asyncio.wait_for(timeout=settings.generator_request_timeout)`; (6) return `QueryResponse`; `finally`: `sidecar.teardown()` + `shutil.rmtree(scratch_dir, ignore_errors=True)`; log at INFO: `POST /kbs/{kb_id}/query question_length={N} elapsed_ms={N} status={code}`

- [ ] T008 [US1] Create `generator_api/app.py`: `create_app()` factory; `_lifespan` validates `DATABASE_URL` + `AZURE_STORAGE_CONNECTION_STRING` via `check_postgres()` + `check_azurite()` and raises `RuntimeError` on failure; logs WARNING if `LLM_API_KEY` is empty; includes `router` (no prefix) and `GET /health` handler returning `HealthResponse` (probes both Postgres and Azurite, returns 200 if both ok, 503 if either fails); registers exception handlers for `BlobSyncError→503`, `SidecarStartError→502`, `asyncio.TimeoutError→504`; module-level `app = create_app()`

---

## Phase 4 — User Story 2: Service Rejects Queries for KBs That Are Not Ready

> Preflight validation is already wired in T007; this phase validates edge-case error responses
> and ensures the exception handler chain is complete.
> **Independent test**: `POST /kbs/{unknown-uuid}/query` → 404; KB with no complete docs → 409; missing `question` → 422.

- [ ] T009 [US2] Add custom exceptions to `generator_api/exceptions.py`: `KBNotFoundError(kb_id)`, `KBNotReadyError(kb_id)`, `BlobSyncError(message)`, `SidecarStartError(message)`, `SidecarQueryError(message)`; update `router.py` to raise `KBNotFoundError` / `KBNotReadyError` from preflight checks; update `app.py` exception handlers to map each custom exception to the correct HTTP status and JSON body matching `specs/003-generator-api/contracts/generator-api-http.md`

- [ ] T010 [US2] Add `kb_id` path-traversal guard in `router.py`: FastAPI path parameter typed as `uuid.UUID` (rejects non-UUIDs and encoded slashes automatically); add explicit check that `str(kb_id)` contains only UUID characters before using in any filesystem or storage path; return 422 if check fails

---

## Phase 5 — User Story 3: Service Runs in Docker Compose Without External Dependencies

> Local-first hard requirement. Service joins the existing Compose stack sharing Postgres + Azurite.
> **Independent test**: `docker compose up` → `GET http://localhost:8001/health` → 200 `{"status":"ok","postgres":"ok","azurite":"ok"}`.

- [ ] T011 [P] [US3] Create `Dockerfile.generator-api`: multi-stage (builder: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`; runtime: `python:3.12-slim-bookworm`); builder stage: `COPY uv.lock pyproject.toml ./`, `COPY openkb/ openkb/`, `COPY generator_api/ generator_api/`, `RUN SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 uv sync --no-dev --frozen --all-extras`; runtime stage: copy `.venv` and source; `useradd -m generator`; `USER generator`; `EXPOSE 8001`; `HEALTHCHECK CMD curl -sf http://localhost:8001/health`; `CMD ["python", "-m", "generator_api"]`

- [ ] T012 [US3] Update `docker-compose.yml`: add `generator-api` service using `Dockerfile.generator-api`, `container_name: openkb-generator-api`, `ports: ["8001:8001"]`, `env_file: .env`, inline `environment` overrides for `DATABASE_URL` (postgres container hostname), `AZURE_STORAGE_CONNECTION_STRING` (azurite container hostname), `AZURE_KB_CONTAINER: openkb`; `depends_on: postgres (healthy), azurite (healthy)`; `healthcheck: curl -sf http://localhost:8001/health`; `restart: unless-stopped`

- [ ] T013 [US3] Update `.env` and `.env.azure.example`: add `GENERATOR_HOST`, `GENERATOR_PORT=8001`, `GENERATOR_REQUEST_TIMEOUT=300`, `SIDECAR_STARTUP_TIMEOUT=30`, `SCRATCH_DIR_ROOT=/tmp/generator-scratch` with comments; ensure `LLM_API_KEY` placeholder is present (was `OPENAI_API_KEY` in the existing file — keep both, with note that generator-api uses `LLM_API_KEY`)

---

## Phase 6 — User Story 4: Standalone Python Process for Debugging

> Inner-loop developer experience — no Docker required once Postgres and Azurite are running.
> **Independent test**: `python -m generator_api` starts on 127.0.0.1:8001; `GET /health` returns 200.

- [ ] T014 [US4] Create `generator_api/__main__.py`: reads `settings.generator_host` and `settings.generator_port`; launches `uvicorn generator_api.app:app --host {host} --port {port} --workers 1`; when `GENERATOR_HOST` is not set, defaults to `127.0.0.1` for standalone safety (prevents accidental `0.0.0.0` binding outside Docker); add note to `specs/003-generator-api/quickstart.md` on how to run standalone

---

## Phase 7 — Polish & Cross-Cutting

- [ ] T015 [P] Create `scripts/test_query.sh`: end-to-end smoke test (mirrors `test_ingest.sh`); (1) check all services up; (2) ensure KB + compiled doc exists (re-use or call `./scripts/test_ingest.sh` if no complete docs); (3) `POST http://localhost:8001/kbs/{KB_ID}/query` with `{"question": "What is this document about?"}` via curl; (4) assert HTTP 200, `answer` non-empty; (5) print answer + citations; exit 0 on success, 1 on failure

- [ ] T016 Verify `GET /health` reflects real Azurite container name: `azurite` inside Docker, `localhost` for standalone; confirm no hard-coded hostnames — all resolved through `AZURE_STORAGE_CONNECTION_STRING`; update `specs/003-generator-api/quickstart.md` with the full end-to-end test commands (build, seed, compile, query)

---

## Dependencies

```
T001 → T002, T003, T004
T002 → T005, T006, T008
T003 → T007
T004 → T007, T008
T005 → T007
T006 → T007
T007 → T008
T008 → T009, T010, T011, T012, T013, T014
T009 → T015
T011 → T012
T014 → T015
T015 → T016
```

**Story independence**:
- US1 (T005–T008): Core query pipeline — must complete first
- US2 (T009–T010): Depends only on US1 router/app being in place
- US3 (T011–T013): Dockerfile + Compose can be written in parallel with US2; needs app to be complete
- US4 (T014): Thin entrypoint; can be added any time after T008

---

## Parallel Execution Examples

**Phase 2** (all three in parallel once T001 done):
```bash
# Terminal 1
implement T002  # config.py

# Terminal 2
implement T003  # db.py

# Terminal 3
implement T004  # models.py
```

**Phase 3 + Dockerfile in parallel**:
```bash
# Main thread
implement T005 → T006 → T007 → T008

# Background
implement T011  # Dockerfile.generator-api (no code deps; needs package structure only)
```
