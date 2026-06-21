# Implementation Plan: Compiler Worker Skeleton (Phase 0)

**Branch**: `003-compiler-worker-skeleton` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/002-compiler-worker-skeleton/spec.md`

## Summary

Build the Phase 0 compiler-worker: a stateless Python service that consumes
compilation jobs from a Redis list queue, drives a per-job OpenKB sidecar
subprocess through `init → add → status` over HTTP on localhost, writes
compiled wiki pages to Blob Storage (Azurite locally), and records all
outcomes in Postgres. Every sidecar is isolated to a unique scratch directory
and dynamic OS-assigned port and is torn down after every job regardless of
outcome. The worker is fully orchestrated by a five-service Docker Compose
stack and is also runnable as `python -m compiler_worker` for local debugging.

## Technical Context

**Language/Version**: Python 3.10+ (matches `requires-python = ">=3.10"` in
`pyproject.toml`; tested on 3.12 in the existing `.venv`)  
**Primary Dependencies** (new in this feature):
- `redis>=5.0.0` — BRPOP-based job queue consumer (`RedisQueueClient`)
- `azure-storage-blob>=12.0.0` — Blob upload/download (Azurite local; Azure
  production via env-var swap; no code change required)
- `httpx>=0.27.0` — async HTTP client for sidecar `init / add / status` calls
- `aiofiles>=23.0.0` — async scratch directory I/O

**Already established (spec 001)**:
- `sqlalchemy[asyncio]>=2.0.0` + `asyncpg>=0.29.0` — async Postgres sessions
- `alembic>=1.13.0` — migration runner

**Storage**: PostgreSQL 15 (`postgres:15-alpine`); Azurite blob storage
(`mcr.microsoft.com/azure-storage/azurite`); Redis 7 (`redis:7-alpine`)  
**Testing**: `pytest` + `pytest-asyncio` (already in `pyproject.toml[dev]`)  
**Target Platform**: Linux container (Docker Compose) + macOS/Linux host
process (standalone debug mode)  
**Project Type**: Background worker service  
**Performance Goals**: Sequential single-job throughput; no concurrency
requirement in Phase 0; SC-001 target < 5 min per document  
**Constraints**: No Azure cloud services in dev; sidecar cleaned up every job;
no per-KB global state between jobs; single hardcoded KB  
**Scale/Scope**: One worker process, one queue consumer, one KB in Phase 0

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

> **Note**: `.specify/memory/constitution.md` is currently an unfilled
> placeholder template — no active governance principles are defined.
> The planning prompt constraints serve as the effective gate criteria for
> Phase 0.

| Implicit Gate | Status | Notes |
|---|---|---|
| Local-first (no Azure in dev) | ✅ PASS | All dev services are Docker Compose local equivalents: Azurite, Redis, Postgres |
| Sidecar isolation (one per job, localhost only) | ✅ PASS | Sidecar spawned and torn down per job; OS-assigned port; unique scratch dir |
| Stateless worker between jobs | ✅ PASS | No globals or open handles survive job boundary; scratch dir deleted on teardown |
| Standalone runnable (`python -m compiler_worker`) | ✅ PASS | `__main__.py` entry point; all config from env vars via `WorkerConfig` |
| Reuse spec 001 schema and session factory | ✅ PASS | `compiler_worker` imports `openkb.db`; no schema redesign |
| Phase 0 ops only: `init` + `add` + `status` | ✅ PASS | `remove`, `recompile`, `lint` are explicitly out of scope |

**Post-Phase 1 re-check**: All gates still pass after data model and contracts
design — no new dependencies or structural decisions violate the above.

## Project Structure

### Documentation (this feature)

```text
specs/002-compiler-worker-skeleton/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── job-queue-message.md    # Redis queue message schema
│   ├── sidecar-http-api.md     # Sidecar HTTP endpoint contracts
│   ├── blob-storage-paths.md   # Blob path conventions
│   └── env-config.md           # Environment variable reference
└── tasks.md             # Phase 2 output (/speckit.tasks — not created here)
```

### Source Code (repository root)

```text
compiler_worker/                   # New top-level package
├── __init__.py
├── __main__.py                    # Entry: python -m compiler_worker
├── config.py                      # WorkerConfig: reads env vars; fails fast
├── worker.py                      # WorkerLoop: startup recovery + BRPOP loop
├── job.py                         # process_job(): orchestrates one job
├── sidecar.py                     # SidecarProcess: spawn, HTTP, teardown
├── queue_client.py                # QueueClient protocol + RedisQueueClient
└── blob_client.py                 # BlobStorageClient (Azurite ↔ Azure swap)

openkb/db/                         # Spec 001 artefact — shared DB layer
├── __init__.py                    # Re-exports: get_session, engine, tables
├── session.py                     # async_sessionmaker over asyncpg / DATABASE_URL
└── models.py                      # SQLAlchemy Core: knowledge_bases, documents,
                                   #   wiki_pages table objects

docker-compose.yml                 # Five-service stack (NEW)
Dockerfile.compiler-worker         # Multi-stage image for compiler-worker (NEW)

tests/
├── integration/
│   └── compiler_worker/
│       ├── conftest.py                # DB, blob, Redis, worker fixtures
│       ├── test_job_lifecycle.py      # US1: happy-path end-to-end
│       ├── test_failure_recording.py  # US2: sidecar error + timeout
│       └── test_stale_recovery.py     # US2 SC3: stale-compiling recovery
└── unit/
    └── compiler_worker/
        ├── test_config.py         # Env var parsing; missing-var errors
        ├── test_sidecar.py        # Port allocation; subprocess; HTTP mocking
        ├── test_queue.py          # BRPOP parsing; malformed message handling
        └── test_blob.py           # Upload / download path construction
```

**Structure Decision**: Two packages in one repository — `openkb` (existing
CLI/library) and `compiler_worker` (new background service). The worker shares
`openkb.db` without a separate package publish step. This is the simplest
layout that satisfies FR-014 (`python -m compiler_worker`) and the Docker
Compose FR-015 single-image boundary.
