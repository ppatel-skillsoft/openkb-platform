# Implementation Plan: Phase 0 Postgres Schema Bootstrap

**Branch**: `002-phase0-postgres-schema` | **Date**: 2026-06-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-phase0-postgres-schema/spec.md`

## Summary

Bootstrap the persistent data layer for OpenKB Enterprise: three Postgres tables (`knowledge_bases`, `documents`, `wiki_pages`) with UUID primary keys, soft-delete via `deleted_at`, and `timestamptz` timestamps throughout. Delivered as versioned Alembic migrations, a Docker Compose local-dev environment (Postgres 15), an async SQLAlchemy Core connection/session factory importable by downstream services, and a standalone seed/fixture helper. The schema is intentionally minimal — no auth, no multi-tenancy — and is forward-compatible with Phase 1 additions (`org_id`, `added_by`) via new migrations.

## Technical Context

**Language/Version**: Python 3.10+ (pyproject.toml `requires-python = ">=3.10"`; targets 3.10–3.13)
**Primary Dependencies**: SQLAlchemy Core 2.x (async, via asyncpg driver), Alembic (migrations), asyncpg (Postgres async driver), python-dotenv (env config)
**Storage**: PostgreSQL 15 in Docker (local dev); Azure Database for PostgreSQL Flexible Server (production)
**Testing**: pytest 9.0.3 + pytest-asyncio 1.3.0 (already in `[project.optional-dependencies] dev`)
**Target Platform**: Linux container (Docker Compose locally; Azure Container Apps in production)
**Project Type**: Shared library module (`openkb/db/`) + migration tooling + dev environment definition
**Performance Goals**: Migration applies in < 5 minutes on a fresh DB (SC-001); seed completes in < 10 seconds (SC-004); connection factory adds no per-query overhead beyond the driver
**Constraints**: No hard-coded credentials — all config via env vars; no code changes between local and production targets; forward-compatible schema (FR-014); no auth/multi-tenancy tables in this phase (FR-015)
**Scale/Scope**: Phase 0 — single scratch knowledge base; schema is designed to become multi-tenant in Phase 1 via additive migrations only

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

> **Note**: The project constitution (`/.specify/memory/constitution.md`) is currently a blank template with no project-specific principles defined. Gates below are derived directly from the feature spec's stated constraints and the existing `research/` design documents.

| Gate | Spec Source | Status |
|------|------------|--------|
| No auth / multi-tenancy tables in Phase 0 | FR-015 | ✅ PASS — `organizations`, `users`, `kb_access`, et al. are explicitly out of scope |
| Local-first: everything runnable via Docker Compose | FR-008, FR-009 | ✅ PASS — Docker Compose is the sole local-dev mechanism; no Azure services required |
| Forward-compatible: Phase 1 adds columns via new migrations, never rewrites Phase 0 | FR-014, SC-006 | ✅ PASS — no Phase 1 columns (`org_id`, `added_by`) are created in this phase |
| No hard-coded credentials | FR-012 | ✅ PASS — all credentials sourced from `DATABASE_URL` env var |
| Python-native tooling only | Spec assumptions section | ✅ PASS — Alembic + SQLAlchemy Core are Python-native; no JVM/Go tooling |
| Soft-delete strategy consistent with research/02-data-model.md | research/02-data-model.md | ✅ PASS — `deleted_at` nullable timestamptz on all three tables |

**Post-Phase 1 re-check**: No violations introduced. `compilation_config` JSONB and text `status` columns align with `research/02-data-model.md` conventions and avoid the migration friction of Postgres ENUM types.

## Project Structure

### Documentation (this feature)

```text
specs/001-phase0-postgres-schema/
├── plan.md              # This file
├── research.md          # Phase 0 output — technology decisions
├── data-model.md        # Phase 1 output — entity definitions and column specs
├── quickstart.md        # Phase 1 output — developer setup guide
├── contracts/           # Phase 1 output — Python API contract for db module
│   └── db-session-factory.md
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
openkb/
└── db/
    ├── __init__.py          # Public exports: engine, get_session, metadata, tables
    ├── engine.py            # create_async_engine factory + AsyncSession factory
    ├── metadata.py          # SQLAlchemy MetaData + Table definitions (knowledge_bases,
    │                        #   documents, wiki_pages) — single source of truth
    └── migrations/
        ├── env.py           # Alembic async env (uses asyncio runner)
        ├── script.py.mako   # Migration file template
        └── versions/
            └── 0001_phase0_initial_schema.py   # Creates all three tables + indexes

scripts/
└── db_seed.py               # Standalone seed/fixture helper (runnable independently
                             #   of migrations, per FR-011)

docker-compose.yml            # Root-level: postgres:15-alpine + migration runner service
.env.example                  # Template for DATABASE_URL and other required env vars
alembic.ini                   # Alembic configuration (points to openkb/db/migrations/)

tests/
└── db/
    ├── __init__.py
    ├── conftest.py          # pytest-asyncio fixtures: engine, session, seeded_db
    ├── test_migrations.py   # Schema validation: column types, nullability, constraints, indexes
    ├── test_seed.py         # Seed idempotency + row count assertions
    ├── test_factory.py      # Connection factory: env-var config, error handling, session lifecycle
    └── test_forward_compat.py  # Stub Phase 1 migration: adds org_id + added_by, verifies SC-006
```

**Structure Decision**: Single-project layout. The `openkb/db/` sub-package slots naturally into the existing `openkb/` package (consistent with `openkb/config.py`, `openkb/schema.py`, etc.) and is importable as `from openkb.db import get_session` by both `compiler-worker` and `generator-api` without any additional packaging changes.

## Complexity Tracking

> No constitution violations identified. No complexity justification required.
