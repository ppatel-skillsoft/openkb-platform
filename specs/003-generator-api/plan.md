# Implementation Plan: Phase 0 Generator API Service

**Branch**: `004-generator-api` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-generator-api/spec.md`

## Summary

Build a single-endpoint FastAPI service (`generator-api`) that accepts `POST /kbs/{kb_id}/query`,
validates the KB exists and has compiled documents in Postgres, syncs the compiled wiki tree from
Azurite to a per-request scratch directory, spawns a dedicated OpenKB sidecar process pointing at
that directory, proxies the question to the sidecar's `POST /kb/query` endpoint, and returns
`{ answer, citations, tokens_used }` to the caller. The service joins the existing Docker Compose
stack (Postgres + Azurite already defined in specs 001–002) as a new container with no new
infrastructure dependencies. Per-request sidecar spin-up is the Phase 0 isolation strategy;
warm pooling is deferred.

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: FastAPI 0.115+, uvicorn[standard], SQLAlchemy Core 2.x (asyncio), asyncpg,
  httpx, azure-storage-blob ≥ 12.19, pydantic-settings, openkb[api] (sidecar, installed in same env)
**Storage**: PostgreSQL 15 — read-only (`knowledge_bases`, `documents` tables via shared session
  factory from spec 001); Azure Blob Storage / Azurite — read-only (wiki tree download)
**Testing**: pytest, pytest-asyncio; httpx.AsyncClient for route tests; `unittest.mock` / subprocess
  mock for sidecar unit tests; Docker Compose stack for integration tests
**Target Platform**: Linux container (Docker Compose), macOS (standalone Python for inner-loop debugging)
**Project Type**: Web service (REST API proxy + orchestration layer)
**Performance Goals**: Phase 0 — low query volume (internal dev use only); request latency is logged
  per request to establish a baseline; no latency SLA in Phase 0
**Constraints**: Per-request sidecar spin-up (warm pool deferred); citations must be preserved
  verbatim (zero-drop guarantee); no auth in Phase 0; local-first via Docker Compose (HARD requirement);
  `save` param is a no-op; path-traversal validation on kb_id before any FS or storage use
**Scale/Scope**: Phase 0 — single developer, sequential queries, 1 KB in practice

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution file (`.specify/memory/constitution.md`) contains only the unpopulated template
skeleton — no principles have been ratified. **No constitutional gates to evaluate for this plan.**

> ⚠️ **Recommendation**: Populate the constitution before spec 004 to formalise principles such as
> local-first, citation fidelity, service isolation, and test-first. Operating without a ratified
> constitution means architectural decisions for this and prior plans carry no governance backstop.

**Post-design re-check** (after Phase 1): No new architectural patterns introduced that would require
justification under any plausible constitution — single service, no shared mutable state, clean
process lifecycle, read-only DB access.

## Project Structure

### Documentation (this feature)

```text
specs/003-generator-api/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/
│   ├── generator-api-http.md   # Public HTTP API contract for this service
│   ├── env-config.md           # Environment variable specification
│   └── sidecar-spawn.md        # Per-request sidecar lifecycle contract
└── tasks.md             # Phase 2 output (/speckit.tasks command — NOT created here)
```

### Inherited Contracts (created here as pre-requisites from specs 001–002)

```text
specs/001-phase0-postgres-schema/
├── data-model.md                        # Postgres schema entities (created in this plan)
└── contracts/
    └── db-session-factory.md            # Shared async session factory contract (created in this plan)

specs/002-compiler-worker-skeleton/
└── contracts/
    ├── blob-storage-paths.md            # Azurite blob layout contract (created in this plan)
    ├── sidecar-http-api.md              # OpenKB sidecar HTTP API contract (created in this plan)
    └── env-config.md                    # Environment variable pattern for worker services (created in this plan)
```

### Source Code (repository root)

```text
generator_api/                      # New Python package — python -m generator_api
├── __init__.py
├── __main__.py                     # Entry: uvicorn app (--host 127.0.0.1 for standalone debug)
├── app.py                          # FastAPI factory + lifespan (Postgres + Azurite health gate)
├── config.py                       # pydantic-settings: all config from env vars, no hard-coded values
├── db.py                           # SQLAlchemy async engine + get_db() dependency (from spec 001 contract)
├── blob.py                         # Wiki-tree sync: Azurite → scratch dir via azure-storage-blob SDK
├── models.py                       # Pydantic: QueryRequest, QueryResponse, ErrorResponse
├── sidecar.py                      # Sidecar lifecycle: spawn, wait-ready, call /kb/query, teardown
└── router.py                       # Routes: POST /kbs/{kb_id}/query, GET /health

Dockerfile.generator-api            # Multi-stage; non-root user; HEALTHCHECK GET /health
docker-compose.yml                  # Updated: add generator-api service (shares pg + azurite)

tests/
├── integration/
│   └── test_query_endpoint.py      # End-to-end: real Compose stack, real query round-trip
└── unit/
    ├── test_db_preflight.py        # Preflight: KB not found → 404, no complete docs → 409
    ├── test_blob_sync.py           # Wiki sync: mock BlobServiceClient, verify scratch layout
    └── test_sidecar.py             # Sidecar lifecycle: mock subprocess + httpx, verify teardown
```

**Structure Decision**: Flat single-package layout (`generator_api/`) mirrors the compiler-worker
pattern from spec 002 (`python -m compiler_worker`). No repository or service-layer abstraction —
direct SQLAlchemy queries in `router.py` are appropriate for Phase 0's read-only, two-table DB
access. All orchestration complexity lives in `sidecar.py` (lifecycle) and `blob.py` (sync).

## Complexity Tracking

> No constitution violations to justify (constitution unpopulated; no gates applicable).
