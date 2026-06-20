---

description: "Task list for FastAPI HTTP API Layer implementation"
---

# Tasks: FastAPI HTTP API Layer

**Feature**: `001-fastapi-http-api`
**Input**: Design documents from `specs/001-fastapi-http-api/`
**Prerequisites**: plan.md ✅ spec.md ✅ data-model.md ✅ contracts/kb-api.md ✅ quickstart.md ✅ research.md ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each increment.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel with other `[P]` tasks in the same phase (different files, no mutual dependency)
- **[US1]–[US4]**: User story label — maps task to spec.md priority story
- Exact file paths are included in every task description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish pyproject.toml changes and create all new package skeletons so every subsequent phase can operate on known file locations.

- [X] T001 Update pyproject.toml — add `fastapi==0.137.2`, `uvicorn[standard]==0.49.0`, `azure-storage-blob[aio]==12.30.0` as `[api]` optional-dependencies extra; add `httpx==0.28.1`, `anyio==4.14.0` to `[dev]` optional-dependencies; include rationale comments per existing pyproject.toml convention in pyproject.toml
- [X] T002 [P] Create openkb/storage/ package skeleton — new files openkb/storage/__init__.py, openkb/storage/base.py, openkb/storage/local.py, openkb/storage/azure_blob.py as empty stubs each starting with `from __future__ import annotations`
- [X] T003 [P] Create openkb/services/ package skeleton — new files openkb/services/__init__.py, openkb/services/init_kb.py, openkb/services/add_document.py, openkb/services/query_kb.py, openkb/services/list_kb.py, openkb/services/status_kb.py as empty stubs each starting with `from __future__ import annotations`
- [X] T004 [P] Create openkb/api/ package skeleton — new files openkb/api/__init__.py, openkb/api/app.py, openkb/api/deps.py, openkb/api/models.py, openkb/api/routes/__init__.py, openkb/api/routes/kb.py as empty stubs each starting with `from __future__ import annotations`

**Checkpoint**: All package directories exist and are importable. `python -c "import openkb.storage, openkb.services, openkb.api"` succeeds.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core abstractions, backend implementations, Pydantic models, app factory, and dependency wiring that MUST be complete before any user story route can be implemented.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. Execution order within the phase is T005 → T006/T007/T008 (parallel once T005 done) → T009 → T010/T011 (parallel once T009 done) → T012 → T013.

- [X] T005 Implement StorageBackend ABC in openkb/storage/base.py — abstract async methods: `read_bytes(path: str) → bytes`, `write_bytes(path: str, content: bytes) → None`, `delete(path: str) → None`, `exists(path: str) → bool`, `list_prefix(prefix: str) → list[str]`, `get_mtime(path: str) → float | None`; abstract async context-manager `lock(resource: str = "ingest", *, timeout: float = 30.0) → AsyncIterator[None]` decorated with `@asynccontextmanager`; non-abstract convenience wrappers `read_text` and `write_text` with default UTF-8 encoding
- [X] T006 [P] Implement service result dataclasses and exception hierarchy in openkb/services/__init__.py — dataclasses: `KBInitResult(status: Literal["created","exists"], kb_name: str, message: str)`, `KBAddResult(status: Literal["added","skipped","failed"], doc_name: str | None, message: str)`, `KBQueryResult(answer: str, saved_to: str | None)`, `DocumentEntry(name: str, doc_name: str, type: str)`, `KBListResult(documents: list[DocumentEntry], summaries: list[str], concepts: list[str], entities: list[str], reports: list[str])`, `KBStatusResult(kb_name: str, total_indexed: int, last_compile: str | None, last_lint: str | None, directory_counts: dict[str,int])`; exception classes: `KBNotFoundError(kb_name)`, `KBAlreadyExistsError(kb_name)`, `UnsupportedDocumentError(ext, supported)`, `URLFetchError(url, detail)`, `LLMError(detail)`, `LockTimeoutError(resource)` all inheriting from a common `OpenKBError(Exception)` base
- [X] T007 [P] Implement LocalStorageBackend in openkb/storage/local.py — extends `StorageBackend`; constructor takes `kb_dir: Path`; all 7 abstract methods wrap `pathlib.Path` operations via `asyncio.to_thread`; `write_bytes` delegates to `atomic_write_bytes` from `openkb.locks` for atomic writes; `lock()` acquires `kb_ingest_lock(kb_dir / ".openkb")` via `asyncio.to_thread`, raises `LockTimeoutError` on `portalocker.exceptions.LockException` after timeout; exposes `kb_dir: Path` as a public property for the compiler-layer bridge
- [X] T008 [P] Implement AzureBlobStorageBackend in openkb/storage/azure_blob.py — extends `StorageBackend`; constructor takes `connection_string: str`, `container_name: str`, `kb_name: str`; lazy `BlobServiceClient` init via `azure.storage.blob.aio`; all blob names scoped as `f"{kb_name}/{path}"`; `write_bytes` uses `upload_blob(overwrite=True)`; `list_prefix` uses `list_blobs(name_starts_with=f"{kb_name}/{prefix}")` and strips the kb_name prefix from returned paths; `lock()` acquires `BlobLeaseClient` on `f"{kb_name}/.openkb/ingest.lock"` with `lease_duration=60`, polls every 1 s up to `timeout`, raises `LockTimeoutError` on expiry, releases in `finally`; `local_working_dir()` async context manager — creates `tempfile.TemporaryDirectory`, downloads all blobs under `kb_name/` into it, yields the `Path`, on exit uploads new/changed files back to blob storage
- [X] T009 Update openkb/storage/__init__.py — export `StorageBackend`, `LocalStorageBackend`, `AzureBlobStorageBackend`; implement `get_backend(kb_name: str, settings) → StorageBackend` factory returning `AzureBlobStorageBackend(connection_string, container_name, kb_name)` when `settings.storage_backend == "azure"` or `LocalStorageBackend(kb_dir=settings.openkb_base_dir / kb_name)` otherwise
- [X] T010 [P] Implement all Pydantic v2 request and response models in openkb/api/models.py — request models: `KBInitRequest(kb_name: str, model: str | None = None, language: str | None = None)` with `kb_name` pattern `^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$|^[a-z0-9]$`; `KBAddRequest(kb_name: str, source: str)`; `KBQueryRequest(kb_name: str, question: str, save: bool = False)` with `question` `min_length=1`; response models: `KBInitResponse`, `KBAddResponse`, `KBQueryResponse`, `DocumentItem(name, doc_name, type)`, `KBListResponse(documents: list[DocumentItem], summaries, concepts, entities, reports)`, `KBStatusResponse(kb_name, total_indexed, last_compile, last_lint, directory_counts)`, `ErrorResponse(detail: str)`; add `field_validator` on `model` and `language` (mode `"before"`) mirroring `_coerce_model`/`_coerce_language` from openkb/cli.py — max 100/50 chars, strip whitespace, reject `\n\r\t` control characters
- [X] T011 [P] Implement `Settings` (Pydantic `BaseSettings`) and `get_backend` FastAPI dependency in openkb/api/deps.py — `Settings` reads `OPENKB_STORAGE_BACKEND` (default `"local"`), `OPENKB_BASE_DIR` (default `Path("/data/kbs")`), `AZURE_STORAGE_CONNECTION_STRING`, `AZURE_KB_CONTAINER` from environment via `python-dotenv`; `get_settings()` cached with `@lru_cache`; `async def get_backend(kb_name: str, settings: Settings = Depends(get_settings)) → StorageBackend` delegates to `openkb.storage.get_backend(kb_name, settings)`
- [X] T012 Implement `create_app()` factory and lifespan in openkb/api/app.py — `FastAPI(title="OpenKB API", version=__version__, lifespan=lifespan)`; lifespan validates `OPENKB_STORAGE_BACKEND` is `"local"` or `"azure"`, for `azure` validates `AZURE_STORAGE_CONNECTION_STRING` and `AZURE_KB_CONTAINER` are set, logs backend choice at INFO; exception handlers: `KBNotFoundError → JSONResponse(404, {"detail": ...})`, `KBAlreadyExistsError → JSONResponse(409)`, `LockTimeoutError → JSONResponse(503)`, `LLMError → JSONResponse(502)`, `UnsupportedDocumentError → JSONResponse(422)`; `include_router(kb_router, prefix="/kb")` where `kb_router` is imported from `openkb.api.routes.kb`
- [X] T013 Add `openkb serve` CLI command to openkb/cli.py — `@cli.command()` with `@click.option("--host", default="0.0.0.0", show_default=True)`, `@click.option("--port", default=8000, type=int, show_default=True)`, `@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev mode)")`; deferred import of `uvicorn` and `openkb.api.app.create_app` inside command body with `ImportError` guard that prints `"The [api] extra is required. Install with: pip install 'openkb[api]'"` and raises `SystemExit(1)`; calls `uvicorn.run(create_app(), host=host, port=port, reload=reload)`

**Checkpoint**: Foundation complete. `from openkb.storage import StorageBackend, LocalStorageBackend, AzureBlobStorageBackend` and `from openkb.api.app import create_app` both succeed. `openkb serve --help` shows `--host`, `--port`, `--reload` options.

---

## Phase 3: User Story 1 — Query KB over HTTP (Priority: P1) 🎯 MVP

**Goal**: `POST /kb/query` accepts a `kb_name` + `question` and returns a structured JSON answer, backed by the existing `run_query` logic. This single endpoint delivers immediate integration value.

**Independent Test**: `POST /kb/query` with a pre-populated `kb_name` against a `LocalStorageBackend` returns `{"answer": "<text>", "saved_to": null}` with HTTP 200. Sending a blank `question` returns HTTP 422. Sending an unknown `kb_name` returns HTTP 404.

- [X] T014 [US1] Implement `service_query_kb(backend: StorageBackend, kb_name: str, question: str, save: bool = False) → KBQueryResult` in openkb/services/query_kb.py — verify KB existence via `await backend.exists(".openkb/config.yaml")`, raise `KBNotFoundError(kb_name)` if absent; for `LocalStorageBackend` call `run_query(question, kb_dir=backend.kb_dir)` directly; for `AzureBlobStorageBackend` use `async with backend.local_working_dir() as kb_dir` around the `run_query` call and sync changed files back on exit; wrap LiteLLM/API exceptions as `LLMError`; if `save=True` write answer to `wiki/explorations/<slug>.md` via `backend.write_text`; return `KBQueryResult(answer=answer, saved_to=saved_path or None)`
- [X] T015 [US1] Update openkb/services/__init__.py — append re-export `from openkb.services.query_kb import service_query_kb`
- [X] T016 [P] [US1] Refactor openkb/cli.py `query` command to call `service_query_kb` — replace inline query logic with `result = asyncio.run(service_query_kb(LocalStorageBackend(kb_dir), kb_name, question, save))`; `click.echo(result.answer)`; catch `KBNotFoundError` → `click.echo(str(e))` and exit; preserve existing CLI UX
- [X] T017 [US1] Implement `POST /kb/query` route handler in openkb/api/routes/kb.py — `async def query_kb(body: KBQueryRequest, backend: StorageBackend = Depends(get_backend)) → KBQueryResponse`; single line: `result = await service_query_kb(backend, body.kb_name, body.question, body.save)`; return `KBQueryResponse(answer=result.answer, saved_to=result.saved_to)`; zero business logic; export `kb_router = APIRouter()` from openkb/api/routes/kb.py

**Checkpoint**: `POST /kb/query` returns 200 with `{"answer": "...", "saved_to": null}`. `POST /kb/query` with `{"question": ""}` returns 422. `POST /kb/query` with unknown `kb_name` returns 404. Existing `openkb query` CLI command works identically.

---

## Phase 4: User Story 2 — Initialise a KB via HTTP (Priority: P2)

**Goal**: `POST /kb/init` creates a new KB directory structure (`.openkb/config.yaml`, `wiki/`, `raw/`, lock blob) and returns a structured confirmation. Enables headless provisioning workflows.

**Independent Test**: `POST /kb/init` against an empty base directory creates the expected structure and returns `{"kb_name": "...", "status": "created", "message": "..."}`. A second call to the same `kb_name` returns HTTP 409.

- [X] T018 [US2] Implement `service_init_kb(backend: StorageBackend, kb_name: str, model: str | None, language: str | None) → KBInitResult` in openkb/services/init_kb.py — check `await backend.exists(".openkb/config.yaml")`; raise `KBAlreadyExistsError(kb_name)` if present; resolve `model` (default `DEFAULT_CONFIG["model"]`) and `language` (default `DEFAULT_CONFIG["language"]`); write `.openkb/config.yaml` (YAML: model, language, pageindex_threshold) via `backend.write_text`; write `.openkb/hashes.json` (`{}`) via `backend.write_text`; write empty `.openkb/ingest.lock` bytes via `backend.write_bytes`; create wiki directory seed files (`wiki/AGENTS.md`, `wiki/index.md`, `wiki/log.md`, prefix stubs for `wiki/summaries/`, `wiki/concepts/`, `wiki/entities/`, `wiki/reports/`, `wiki/sources/images/`) using `AGENTS_MD` and `INDEX_SEED` constants from `openkb.schema`; write empty `raw/.gitkeep`; return `KBInitResult(status="created", kb_name=kb_name, message=f"Knowledge base '{kb_name}' initialised.")`
- [X] T019 [US2] Update openkb/services/__init__.py — append re-export `from openkb.services.init_kb import service_init_kb`
- [X] T020 [P] [US2] Refactor openkb/cli.py `init` command to call `service_init_kb` — replace inline init logic with `result = asyncio.run(service_init_kb(LocalStorageBackend(kb_dir), kb_name, model, language))`; `click.echo(result.message)`; catch `KBAlreadyExistsError` → `click.echo("Knowledge base already initialized.")`; preserve existing CLI UX and `--model`, `--language` option names
- [X] T021 [US2] Implement `POST /kb/init` route handler in openkb/api/routes/kb.py — `async def init_kb(body: KBInitRequest, backend: StorageBackend = Depends(get_backend)) → KBInitResponse`; delegates to `service_init_kb(backend, body.kb_name, body.model, body.language)`; return `KBInitResponse(kb_name=result.kb_name, status=result.status, message=result.message)`; zero business logic

**Checkpoint**: `POST /kb/init` returns 200 with `{"kb_name":"...","status":"created","message":"..."}`. Second call returns 409. `POST /kb/init` with `kb_name` containing uppercase returns 422. Existing `openkb init` CLI command works identically.

---

## Phase 5: User Story 3 — Add a Document via HTTP (Priority: P2)

**Goal**: `POST /kb/add` ingests a document (local file path or `http(s)://` URL) into an existing KB, acquiring the distributed lock, compiling the document, and returning `{"status": "added"|"skipped", "doc_name": "..."}`.

**Independent Test**: `POST /kb/add` with a known Markdown file path against an initialised `kb_name` returns 200 with `{"status": "added", "doc_name": "..."}`. A second call with the same file returns `{"status": "skipped"}`. Sending a `.zip` source returns 422.

- [X] T022 [US3] Implement `service_add_document(backend: StorageBackend, kb_name: str, source: str) → KBAddResult` in openkb/services/add_document.py — verify KB existence via `backend.exists(".openkb/config.yaml")`, raise `KBNotFoundError` if absent; if `source` starts with `http://` or `https://` fetch bytes with `httpx.AsyncClient`, raise `URLFetchError` on non-200 or network error; determine file extension, raise `UnsupportedDocumentError(ext, SUPPORTED_EXTENSIONS)` if not in registry; compute SHA-256 hash of content bytes; load `hashes.json` via `backend.read_bytes`; return `KBAddResult(status="skipped", ...)` if hash already present; acquire `async with backend.lock()`; write source bytes to `raw/<filename>`; for `LocalStorageBackend` call `convert_document` then `compile_short_doc` or `compile_long_doc` passing `backend.kb_dir`; for `AzureBlobStorageBackend` use `async with backend.local_working_dir() as kb_dir` around compile calls; update `hashes.json` atomically; return `KBAddResult(status="added", doc_name=doc_name, ...)`; wrap LiteLLM errors as `LLMError`
- [X] T023 [US3] Update openkb/services/__init__.py — append re-export `from openkb.services.add_document import service_add_document`
- [X] T024 [P] [US3] Refactor openkb/cli.py `add` command — replace `add_single_file` / `_add_single_file_locked` inline logic with `asyncio.run(service_add_document(LocalStorageBackend(kb_dir), kb_name, source))`; preserve thin sync `add_single_file(file_path: str, kb_dir: Path) → None` wrapper that calls `asyncio.run(service_add_document(...))` for backward compatibility with any existing callers; `click.echo` the status message; preserve the URL and wildcard expansion logic in the Click command wrapper
- [X] T025 [US3] Implement `POST /kb/add` route handler in openkb/api/routes/kb.py — `async def add_document(body: KBAddRequest, backend: StorageBackend = Depends(get_backend)) → KBAddResponse`; delegates to `service_add_document(backend, body.kb_name, body.source)`; return `KBAddResponse(status=result.status, doc_name=result.doc_name, message=result.message)`; zero business logic

**Checkpoint**: `POST /kb/add` returns 200 with `{"status":"added","doc_name":"...","message":"..."}`. Duplicate add returns `{"status":"skipped"}`. Unsupported extension returns 422. Unknown `kb_name` returns 404. Existing `openkb add` CLI command works identically.

---

## Phase 6: User Story 4 — List and Status via HTTP (Priority: P3)

**Goal**: `GET /kb/list` and `GET /kb/status` return structured read-only snapshots of a KB's content inventory and health metrics — enabling monitoring dashboards and operator tooling.

**Independent Test**: `GET /kb/list?kb_name=<name>` against a KB with at least one compiled document returns 200 with all five array fields present. `GET /kb/status?kb_name=<name>` returns 200 with `total_indexed`, `last_compile`, `last_lint`, and `directory_counts`. Both return 404 for an unknown `kb_name`.

- [X] T026 [P] [US4] Implement `service_list_kb(backend: StorageBackend, kb_name: str) → KBListResult` in openkb/services/list_kb.py — verify KB existence; raises `KBNotFoundError` if absent; read `hashes.json` via `backend.read_bytes` to build `documents: list[DocumentEntry]` (name, doc_name, type from registry); list `wiki/summaries/`, `wiki/concepts/`, `wiki/entities/`, `wiki/reports/` via `backend.list_prefix()`, extract sorted stems; return `KBListResult(documents, summaries, concepts, entities, reports)` mirroring the data previously formatted by `print_list(kb_dir)` in openkb/cli.py
- [X] T027 [P] [US4] Implement `service_status_kb(backend: StorageBackend, kb_name: str) → KBStatusResult` in openkb/services/status_kb.py — verify KB existence; raises `KBNotFoundError` if absent; read `hashes.json` via `backend.read_bytes` for `total_indexed = len(registry)`; call `backend.get_mtime()` on each file returned by `backend.list_prefix("wiki/summaries")` + `wiki/concepts` + `wiki/entities`, take max as `last_compile` (ISO-8601 UTC string or None); call `backend.get_mtime()` on `wiki/reports/` files for `last_lint`; count files per subdirectory via `len(await backend.list_prefix(subdir))` for `sources`, `summaries`, `concepts`, `entities`, `reports`, `raw`; return `KBStatusResult(kb_name, total_indexed, last_compile, last_lint, directory_counts)` mirroring data from `print_status(kb_dir)` in openkb/cli.py
- [X] T028 [US4] Update openkb/services/__init__.py — append re-exports `from openkb.services.list_kb import service_list_kb` and `from openkb.services.status_kb import service_status_kb`
- [X] T029 [P] [US4] Refactor openkb/cli.py `list` command — replace `print_list(kb_dir)` function body with `result = asyncio.run(service_list_kb(LocalStorageBackend(kb_dir), kb_name))`; format and `click.echo` the result fields preserving existing output format; update all call sites of `print_list` in openkb/cli.py (including the chat REPL) to use the service function directly
- [X] T030 [P] [US4] Refactor openkb/cli.py `status` command — replace `print_status(kb_dir)` function body with `result = asyncio.run(service_status_kb(LocalStorageBackend(kb_dir), kb_name))`; format and `click.echo` the result fields preserving existing output format; update all call sites of `print_status` in openkb/cli.py (including the chat REPL) to use the service function directly
- [X] T031 [US4] Implement `GET /kb/list` and `GET /kb/status` route handlers in openkb/api/routes/kb.py — `async def list_kb(kb_name: str = Query(..., pattern=r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$|^[a-z0-9]$"), backend: StorageBackend = Depends(get_backend)) → KBListResponse`; `async def status_kb(kb_name: str = Query(...), backend: StorageBackend = Depends(get_backend)) → KBStatusResponse`; both delegate entirely to the respective service functions; zero business logic

**Checkpoint**: `GET /kb/list?kb_name=<name>` returns 200 with `documents`, `summaries`, `concepts`, `entities`, `reports` arrays. `GET /kb/status?kb_name=<name>` returns 200 with all required fields. Both return 404 for unknown `kb_name`. Existing `openkb list` and `openkb status` CLI commands work identically.

---

## Phase 7: Docker & Local-First Deployment

**Purpose**: Package the API as a Docker image and wire the full local development stack (API + Azurite) with `docker compose up` as documented in quickstart.md.

- [X] T032 Create Dockerfile at repository root — `FROM python:3.12-slim`; `COPY pyproject.toml uv.lock ./` and `COPY openkb/ ./openkb/`; `RUN pip install --no-cache-dir ".[api]"`; `EXPOSE 8000`; `CMD ["openkb", "serve", "--host", "0.0.0.0", "--port", "8000"]`; add `.dockerignore` excluding `.git`, `__pycache__`, `*.pyc`, `tests/`, `specs/`, `.env`
- [X] T033 Create docker-compose.yml at repository root — `azurite` service: `image: mcr.microsoft.com/azure-storage/azurite:latest`, `command: azurite-blob --blobHost 0.0.0.0`, `ports: ["10000:10000"]`, healthcheck `test: ["CMD-SHELL", "nc -z localhost 10000"]` interval 5s retries 3; `api` service: `build: .`, `env_file: .env`, `ports: ["8000:8000"]`, `depends_on: {azurite: {condition: service_healthy}}`, `restart: unless-stopped`, healthcheck `test: ["CMD", "curl", "-sf", "http://localhost:8000/docs"]` interval 10s start_period 15s; both services on a named bridge network `openkb-net`
- [X] T034 [P] Create .env.docker at repository root — pre-filled Azurite connection string: `AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=<AZURITE_DEV_KEY>;BlobEndpoint=http://azurite:10000/devstoreaccount1`; `OPENKB_STORAGE_BACKEND=azure`; `AZURE_KB_CONTAINER=openkb`; `LLM_API_KEY=` (empty placeholder with comment `# Fill in your LLM API key — OpenAI, Anthropic, etc.`); file contains no real secrets and is safe to commit
- [X] T035 [P] Create .env.azure.example at repository root — production Azure template: `OPENKB_STORAGE_BACKEND=azure`; `AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=<your-account>;AccountKey=<your-key>;EndpointSuffix=core.windows.net` (placeholder, never a real key); `AZURE_KB_CONTAINER=openkb`; `LLM_API_KEY=sk-...` placeholder; add header comment block directing users to copy to `.env` and replace values; verify `.gitignore` excludes `.env` and `.env.azure` (real credential files) while tracking `.env.docker` and `.env.azure.example`

**Checkpoint**: `docker compose up` starts both services. `curl http://localhost:8000/docs` returns the FastAPI Swagger UI. `curl -X POST http://localhost:8000/kb/init -H "Content-Type: application/json" -d '{"kb_name":"smoke-test"}'` returns 200. `docker compose down` tears the stack down cleanly.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final wiring, export hygiene, and secret-file protection.

- [ ] T036 [P] Finalize all `__init__.py` re-exports — `openkb/storage/__init__.py` exports `StorageBackend`, `LocalStorageBackend`, `AzureBlobStorageBackend`, `get_backend`; `openkb/services/__init__.py` exports all 5 service functions (`service_init_kb`, `service_add_document`, `service_query_kb`, `service_list_kb`, `service_status_kb`), all 6 exception classes, and all result dataclasses (`KBInitResult`, `KBAddResult`, `KBQueryResult`, `DocumentEntry`, `KBListResult`, `KBStatusResult`); `openkb/api/__init__.py` exports `create_app`; `openkb/api/routes/__init__.py` exports `kb_router`; add module-level docstrings to each `__init__.py`
- [ ] T037 [P] Update .gitignore — add `.env` and `.env.azure` (real-credential files must never be committed); confirm `.env.docker` and `.env.azure.example` are NOT in `.gitignore` (they are intentionally tracked template files); add `__pycache__/`, `*.pyc`, `.pytest_cache/`, `dist/`, `*.egg-info/` if not already present in .gitignore

**Checkpoint**: `git status` shows `.env` as untracked/ignored. `python -m pytest --collect-only` discovers test files without import errors. `openkb --help` lists `init`, `add`, `query`, `list`, `status`, and `serve` commands.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately; T002/T003/T004 run in parallel
- **Foundational (Phase 2)**: Depends on Phase 1 — **BLOCKS all user stories**
  - T005 first; T006/T007/T008 parallel once T005 done; T009 after T007+T008; T010/T011 parallel after T009; T012 after T010+T011; T013 after T012
- **User Stories (Phases 3–6)**: All depend on Foundational (Phase 2) completion
  - Phase 3 (US1 P1), Phase 4 (US2 P2), Phase 5 (US3 P2), Phase 6 (US4 P3) can proceed in priority order or in parallel if staffed
- **Docker (Phase 7)**: Depends on all user story routes being implemented (Phases 3–6 complete)
- **Polish (Phase 8)**: Depends on Phases 1–7 complete; T036/T037 parallel

### User Story Dependencies

| Story | Priority | Depends on | Independent? |
|---|---|---|---|
| US1 — Query | P1 | Phase 2 only | ✅ Fully independent |
| US2 — Init | P2 | Phase 2 only | ✅ Fully independent |
| US3 — Add | P2 | Phase 2 only (uses hash logic from services) | ✅ Fully independent |
| US4 — List + Status | P3 | Phase 2 only | ✅ Fully independent |

### Within Each User Story

1. Service function (`T014`, `T018`, `T022`, `T026/T027`) — must come first
2. Services `__init__.py` re-export (`T015`, `T019`, `T023`, `T028`) — after service file
3. CLI refactor (`T016`, `T020`, `T024`, `T029/T030`) [P] — can run in parallel with route handler
4. Route handler (`T017`, `T021`, `T025`, `T031`) — after service + after T012

---

## Parallel Execution Examples

### Phase 2 Parallel Window (after T005)

```
Parallel after T005 completes:
  Task A: T006 — openkb/services/__init__.py (result types + exceptions)
  Task B: T007 — openkb/storage/local.py (LocalStorageBackend)
  Task C: T008 — openkb/storage/azure_blob.py (AzureBlobStorageBackend)

Merge barrier: T009 (storage/__init__.py) — needs T007 + T008 done
```

### Phase 2 Second Parallel Window (after T009)

```
Parallel after T009 completes:
  Task A: T010 — openkb/api/models.py (all Pydantic models)
  Task B: T011 — openkb/api/deps.py (Settings + get_backend dep)

Merge barrier: T012 (app.py factory) — needs T010 + T011 done
```

### Per User Story Parallel Pair (exemplar for US1)

```
After T014 (service_query_kb) completes:
  Task A: T016 [P] — openkb/cli.py query refactor (different file from routes/kb.py)
  Task B: T017     — openkb/api/routes/kb.py POST /kb/query handler

Both complete independently; no merge barrier needed.
```

### Phase 6 Parallel Services (US4)

```
Parallel — different files, no mutual dependency:
  Task A: T026 [P] — openkb/services/list_kb.py
  Task B: T027 [P] — openkb/services/status_kb.py

After both complete:
  Task C: T028 — openkb/services/__init__.py re-exports (depends on A + B)

Then parallel:
  Task D: T029 [P] — cli.py list refactor
  Task E: T030 [P] — cli.py status refactor

After D + E:
  Task F: T031 — routes/kb.py GET /kb/list + GET /kb/status handlers
```

---

## Implementation Strategy

### MVP First (User Story 1 — Query Only)

1. Complete Phase 1: Setup (~4 tasks)
2. Complete Phase 2: Foundational (~9 tasks, CRITICAL blocker)
3. Complete Phase 3: US1 Query endpoint (~4 tasks)
4. **STOP and VALIDATE**: `POST /kb/query` works end-to-end; CLI `openkb query` unaffected
5. Demo/integrate immediately — the most common integration target is live

### Incremental Delivery

```
Phase 1 + 2 → Foundation ready
    ↓
Phase 3 (US1)  → Query endpoint live — first HTTP integration target ✓
    ↓
Phase 4 (US2)  → Init endpoint live — headless provisioning unblocked ✓
    ↓
Phase 5 (US3)  → Add endpoint live — full ingest pipeline exposed ✓
    ↓
Phase 6 (US4)  → List + Status live — monitoring dashboard support ✓
    ↓
Phase 7        → Docker stack — `docker compose up` local dev path ✓
    ↓
Phase 8        → Polish — export hygiene, .gitignore guard ✓
```

### Parallel Team Strategy (4 developers after Phase 2)

```
Developer A: Phase 3 (US1 — Query)
Developer B: Phase 4 (US2 — Init)
Developer C: Phase 5 (US3 — Add)
Developer D: Phase 6 (US4 — List + Status)

All stories integrate independently into the shared route file and services/__init__.py.
Each developer works on their own service file and route handler.
```

---

## Task Summary

| Phase | Tasks | Count |
|---|---|---|
| Phase 1: Setup | T001–T004 | 4 |
| Phase 2: Foundational | T005–T013 | 9 |
| Phase 3: US1 — Query (P1) | T014–T017 | 4 |
| Phase 4: US2 — Init (P2) | T018–T021 | 4 |
| Phase 5: US3 — Add (P2) | T022–T025 | 4 |
| Phase 6: US4 — List + Status (P3) | T026–T031 | 6 |
| Phase 7: Docker & Deployment | T032–T035 | 4 |
| Phase 8: Polish | T036–T037 | 2 |
| **Total** | T001–T037 | **37** |

| Metric | Value |
|---|---|
| Total tasks | 37 |
| Tasks for US1 (P1) | 4 |
| Tasks for US2 (P2) | 4 |
| Tasks for US3 (P2) | 4 |
| Tasks for US4 (P3) | 6 |
| Parallel opportunities | 14 tasks marked [P] |
| MVP scope (US1 only) | Phases 1+2+3 = 17 tasks |
