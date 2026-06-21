# Implementation Plan: FastAPI HTTP API Layer

**Branch**: `001-fastapi-http-api` | **Date**: 2026-06-19 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-fastapi-http-api/spec.md`

## Summary

Add a FastAPI HTTP API layer to OpenKB so the five core operations (init, add,
query, list, status) are accessible as HTTP endpoints without the CLI. The
implementation introduces a `StorageBackend` abstraction (local filesystem +
Azure Blob Storage), a shared service layer extracted from `cli.py`, and a
new `openkb serve` command that starts a uvicorn ASGI server. FastAPI, uvicorn,
and `azure-storage-blob` are added as an optional `[api]` extra so the base CLI
install stays lightweight.

## Technical Context

**Language/Version**: Python 3.12; `from __future__ import annotations` in
all new modules (existing convention throughout `openkb/`).

**Primary Dependencies (new — `[api]` extra)**:
- `fastapi==0.137.2` — ASGI web framework; requires Pydantic v2 (`>=2.9.0`)
- `uvicorn[standard]==0.49.0` — ASGI server (uvloop + httptools on Linux/macOS)
- `azure-storage-blob==12.30.0` — Azure Blob Storage SDK; use `[aio]` extra
  for the async `BlobServiceClient`

**Primary Dependencies (test additions to `[dev]` extra)**:
- `httpx==0.28.1` — async HTTP client required by FastAPI's `TestClient`
- `anyio==4.14.0` — async test fixtures (`pytest-anyio` plugin)

**Existing Dependencies (unchanged)**:
- `portalocker==3.2.0` — local filesystem advisory locking (CLI path)
- `click==8.4.0` — CLI entry points
- `litellm==1.87.2` — LLM routing (pulls in Pydantic v2 transitively)
- `pyyaml==6.0.3` — YAML config
- `python-dotenv==1.2.2` — `.env` loading

**Storage**: Dual-backend — `LocalStorageBackend` wraps `pathlib.Path` +
`portalocker`; `AzureBlobStorageBackend` wraps `BlobServiceClient` async +
Blob Lease API for distributed locking.

**Testing**: `pytest==9.0.3` + `pytest-asyncio==1.3.0` (existing) +
`httpx==0.28.1` + `anyio==4.14.0` (new dev additions). Test files mirror
source tree per constitution.

**Target Platform**: Linux/macOS server (uvloop available); developer machine
(uvloop excluded on Windows automatically via env markers in uvicorn's `[standard]` extra).

**Project Type**: CLI (existing) + web-service (new API surface). The CLI
remains the primary interface; the API is a second consumer of a shared
service core.

**Performance Goals**: First request within 5 s of `openkb serve` on a
developer machine (SC-002). No data corruption under concurrent writes
(SC-005). No polling — distributed locking via Azure Blob Lease is the
coordination primitive.

**Constraints**: Zero regressions in existing CLI behaviour (FR-012, SC-004).
Switching backends requires only env-var changes — no code changes (FR-015,
SC-007). No auth layer in this version (Assumption).

**Scale/Scope**: Single-process server initially; multiple concurrent API
instances are safe via Azure Blob leases.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| I | **Layered Architecture** — CLI and API are thin adapters; cross-layer deps flow downward only. | ✅ PASS | `StorageBackend` → `services/` → `api/routes/` (downward). CLI uses same services. No shared mutable globals across layers. |
| II | **CLI-First, API-Consistent** — API exposes same operations, same business rules as CLI. | ✅ PASS | Service functions are extracted from `cli.py` and called by both CLI and API. Route handlers contain zero business logic. |
| III | **Async by Default for I/O** — All I/O-bound ops use `async`/`await`. | ✅ PASS | All service functions async. `LocalStorageBackend` wraps sync portalocker calls in `asyncio.to_thread`. `AzureBlobStorageBackend` uses native async SDK. CLI entry points remain the only sync-wrapping boundary (`asyncio.run`). |
| IV | **Test Coverage Non-Negotiable** — Unit + integration + contract tests per module. | ✅ PASS | Plan includes: unit tests for both backends + all 5 service functions; integration tests for all 5 route handlers; contract tests asserting on response schemas. |
| V | **Supply-Chain Discipline** — All deps pinned exactly, rationale comments required. | ✅ PASS | All new deps pinned to exact versions (see Technical Context above). Rationale comments are written into `pyproject.toml` per convention. |
| VI | **Robustness and Graceful Degradation** — Atomic writes; distributed locking; actionable errors. | ✅ PASS | `LocalStorageBackend.write_bytes` delegates to existing `atomic_write_bytes`. `AzureBlobStorageBackend` uses Blob Lease for serialised writes. All error paths return `ErrorResponse` with actionable `detail`. 503 on lease timeout; never silent corruption. |

**No violations — gate is clear.**

## Project Structure

### Documentation (this feature)

```text
specs/001-fastapi-http-api/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── kb-api.md        # Phase 1 API contract (all 5 endpoints)
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
openkb/
├── storage/
│   ├── __init__.py          # exports StorageBackend, LocalStorageBackend,
│   │                        #   AzureBlobStorageBackend, get_backend()
│   ├── base.py              # StorageBackend ABC (read, write, delete, exists,
│   │                        #   list_prefix, get_mtime, lock context manager)
│   ├── local.py             # LocalStorageBackend — pathlib + portalocker
│   └── azure_blob.py        # AzureBlobStorageBackend — azure-storage-blob
│                            #   async client + Blob Lease locking
│                            #   (works unchanged against Azurite + real Azure)
├── services/
│   ├── __init__.py          # re-exports all five service functions
│   ├── init_kb.py           # service_init_kb(backend, model, language) → KBInitResult
│   ├── add_document.py      # service_add_document(backend, source, kb_dir) → KBAddResult
│   ├── query_kb.py          # service_query_kb(backend, question, save, kb_dir) → KBQueryResult
│   ├── list_kb.py           # service_list_kb(backend, kb_dir) → KBListResult
│   └── status_kb.py         # service_status_kb(backend, kb_dir) → KBStatusResult
├── api/
│   ├── __init__.py
│   ├── app.py               # create_app() factory; lifespan; exception handlers
│   ├── deps.py              # FastAPI dependency: get_backend(kb_name) → StorageBackend
│   ├── models.py            # All Pydantic request / response models
│   └── routes/
│       ├── __init__.py
│       └── kb.py            # 5 route handlers — zero business logic
└── cli.py                   # existing (refactored: print_list/print_status → service calls;
│                            #   init/add/query call new service layer; add `serve` command)
│
tests/
├── conftest.py              # existing
├── unit/
│   ├── test_storage_local.py        # LocalStorageBackend: read/write/delete/list/lock
│   ├── test_storage_azure.py        # AzureBlobStorageBackend: mocked BlobServiceClient
│   ├── test_service_init.py         # service_init_kb: created/exists/validation
│   ├── test_service_add.py          # service_add_document: added/skipped/failed/URL
│   ├── test_service_query.py        # service_query_kb: answer/save/empty-state
│   ├── test_service_list.py         # service_list_kb: documents/summaries/concepts/entities
│   └── test_service_status.py       # service_status_kb: counts/timestamps
├── integration/
│   ├── test_api_init.py             # POST /kb/init: 200/409/422
│   ├── test_api_add.py              # POST /kb/add: 200/422/404/502
│   ├── test_api_query.py            # POST /kb/query: 200/404/422/502
│   ├── test_api_list.py             # GET /kb/list: 200/404
│   └── test_api_status.py           # GET /kb/status: 200/404
└── contract/
    └── test_api_contracts.py        # schema assertions per endpoint

# Docker / local-first deployment
Dockerfile                   # API image — installs openkb[api]; runs `openkb serve`
docker-compose.yml           # Two services: api + azurite (Blob emulator)
.env.docker                  # Example env for docker compose (Azurite connection string)
.env.azure.example           # Example env for real Azure deployment (not committed with secrets)
```

**Structure Decision**: Single-project layout extending the existing `openkb/`
package. Two new top-level sub-packages (`storage/`, `services/`) sit alongside
existing modules. The `api/` sub-package is a second surface. Docker artefacts
live at the repository root. Tests are extended in-place under `tests/` with new
sub-directories to mirror the new source tree.

**Local development path**:
1. `docker compose up` — starts API (port 8000) + Azurite (port 10000)
2. `AzureBlobStorageBackend` connects to Azurite via `AZURE_STORAGE_CONNECTION_STRING`
   in `.env.docker` — no Azure account required
3. To promote to real Azure: replace `AZURE_STORAGE_CONNECTION_STRING` in `.env` and
   redeploy — zero code changes

## Complexity Tracking

> No constitution violations — this table is intentionally empty.
