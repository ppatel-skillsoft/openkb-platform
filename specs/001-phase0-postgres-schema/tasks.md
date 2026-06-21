---
description: "Task list for Phase 0 Postgres Schema Bootstrap"
---

# Tasks: Phase 0 Postgres Schema Bootstrap

**Feature**: `002-phase0-postgres-schema`
**Input**: `specs/001-phase0-postgres-schema/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅, contracts/db-session-factory.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`US1`–`US4`)
- Exact file paths included in all descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Install dependencies and scaffold the new sub-package skeleton before any implementation begins.

- [X] T001 Add `db` optional-dependency group to `pyproject.toml` with `sqlalchemy[asyncio]==2.0.x`, `asyncpg==0.30.x`, `alembic==1.14.x` (exact versions to resolve at implementation time; add rationale comments matching existing style)
- [X] T002 Initialise Alembic: run `alembic init openkb/db/migrations` to generate `alembic.ini` at the repository root and the `openkb/db/migrations/` scaffold; configure `alembic.ini` so `script_location = openkb/db/migrations` and `sqlalchemy.url` is left as an env-var placeholder (will be overridden in `env.py`)
- [X] T003 [P] Create `openkb/db/__init__.py` as an empty module placeholder (will receive public exports in Phase 5)
- [X] T004 [P] Create `tests/db/__init__.py` as an empty module placeholder
- [X] T005 [P] Create `scripts/` directory with `scripts/__init__.py` (empty) to make it a recognisable Python scripts location

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define the SQLAlchemy `MetaData` + all three `Table` objects. Every subsequent phase (migration file, session factory, tests) imports from this module — nothing else can begin until it exists.

**⚠️ CRITICAL**: Phases 3–6 cannot begin until this phase is complete.

- [X] T006 Create `openkb/db/metadata.py`: define a single `MetaData()` instance and the three `Table` objects (`knowledge_bases`, `documents`, `wiki_pages`) exactly matching the column specs in `data-model.md` — UUID PKs with `server_default=text("gen_random_uuid()")`, `TIMESTAMPTZ` timestamps, `JSONB` for `compilation_config`, `Boolean`, `Integer`, `Text`, all nullability rules, `UniqueConstraint("kb_id", "slug", name="uq_wiki_pages_kb_id_slug")` on `wiki_pages`, FK `documents.kb_id → knowledge_bases.id` with `index=True`, FK `wiki_pages.kb_id → knowledge_bases.id` with `index=True`; export `metadata`, `knowledge_bases`, `documents`, `wiki_pages`

**Checkpoint**: `metadata.py` ready — all remaining phases can proceed.

---

## Phase 3: User Story 1 — Schema Applied to a Fresh Database (Priority: P1) 🎯 MVP

**Goal**: A single `alembic upgrade head` command against an empty Postgres 15 database creates all three tables with correct structure, constraints, and indexes — and is idempotent on re-runs.

**Independent Test**: Run migration against an empty DB → verify `knowledge_bases`, `documents`, `wiki_pages` tables exist with all specified columns, types, nullability, PKs, FKs, unique constraints, and indexes. Run again → no error, no schema change.

### Implementation for User Story 1

- [X] T007 [US1] Configure `openkb/db/migrations/env.py` for async Alembic: import `metadata` from `openkb.db.metadata`; implement `run_async_migrations()` using `asyncio.run()`; read `DATABASE_URL` from environment (via `python-dotenv`); set `target_metadata = metadata` for autogenerate support; use `asyncpg` driver URL
- [X] T008 [US1] Write migration `openkb/db/migrations/versions/0001_phase0_initial_schema.py`: `upgrade()` creates `knowledge_bases`, then `documents`, then `wiki_pages` in dependency order (matching `data-model.md` Migration Plan); `downgrade()` drops in reverse order; revision message `"phase0 initial schema"`

### Tests for User Story 1

- [X] T009 [P] [US1] Create `tests/db/conftest.py` with `pytest-asyncio` fixtures: `engine` (creates async engine from `DATABASE_URL`), `connection` (yields `AsyncConnection` for test isolation via `begin_nested`), `session` (yields `AsyncSession` per test), `seeded_db` (runs seed logic against test DB); mark module with `pytestmark = pytest.mark.asyncio`
- [X] T010 [P] [US1] Write `tests/db/test_migrations.py`: use `sqlalchemy inspect` via `AsyncConnection` to assert all three tables exist; validate every column name, type, nullability, and server-default per `data-model.md`; assert UNIQUE constraint on `knowledge_bases.slug`; assert UNIQUE constraint `uq_wiki_pages_kb_id_slug` on `wiki_pages(kb_id, slug)`; assert FK `documents.kb_id → knowledge_bases.id`; assert FK `wiki_pages.kb_id → knowledge_bases.id`; assert B-tree indexes on `documents.kb_id` and `wiki_pages.kb_id`; assert idempotency by running `alembic upgrade head` twice without error

**Checkpoint**: US1 independently testable — `uv run pytest tests/db/test_migrations.py -v` passes.

---

## Phase 4: User Story 2 — Local Dev Environment Spun Up in One Step (Priority: P1)

**Goal**: `docker compose up --wait` starts Postgres 15, applies migrations automatically, and leaves a fully usable dev database. Restarts preserve data. Seed command works independently.

**Independent Test**: On a clean machine with Docker, run `docker compose up --wait`; verify `psql \dt` shows `alembic_version`, `documents`, `knowledge_bases`, `wiki_pages`; run `python scripts/db_seed.py`; verify 1 KB row and 2 document rows are queryable.

### Implementation for User Story 2

- [X] T011 [US2] Update `docker-compose.yml` to add two new services alongside the existing `azurite` and `api` services: `postgres` service using `postgres:15-alpine`, named volume `pgdata` for persistence, health check `pg_isready -U ${POSTGRES_USER}` (interval 5s, retries 10), port `5432:5432`, env vars from `.env`; `migrate` service running `alembic upgrade head` with `depends_on: postgres: condition: service_healthy` and `restart: on-failure`; add `pgdata` to the top-level `volumes` block
- [X] T012 [P] [US2] Update `.env.example` to add the Postgres connection block below the existing LLM vars: `DATABASE_URL=postgresql+asyncpg://openkb:openkb@localhost:5432/openkb`, `POSTGRES_USER=openkb`, `POSTGRES_PASSWORD=openkb`, `POSTGRES_DB=openkb`; add a comment block matching the existing doc style
- [X] T013 [US2] Write `scripts/db_seed.py`: import `openkb.db` (`get_session`, `knowledge_bases`, `documents`); insert 1 `knowledge_bases` row (`name="Scratch KB"`, `slug="scratch-kb"`, `status="active"`, `git_versioning_enabled=True`, `compilation_config={"language":"en","pageindex_threshold":0.5,"entity_types":["person","organization"],"extra_headers":{}}`) using `INSERT … ON CONFLICT (slug) DO NOTHING`; insert 2 `documents` rows (one `source_type="pdf"` `status="complete"`, one `source_type="url"` `status="pending"`) checking for existing `kb_id + source_uri` before insert (idempotency per Decision 7); print `[seed]` progress lines per `quickstart.md`; load `.env` via `python-dotenv`

### Tests for User Story 2

- [X] T014 [P] [US2] Write `tests/db/test_seed.py`: call seed logic twice against test DB via `seeded_db` fixture; assert exactly 1 row in `knowledge_bases` with `slug="scratch-kb"`; assert exactly 2 rows in `documents` with the expected `source_type` values; assert running seed a second time leaves row counts unchanged (idempotency SC-004)

**Checkpoint**: US2 independently testable — `docker compose up --wait` and `python scripts/db_seed.py` succeed on a clean clone.

---

## Phase 5: User Story 3 — Shared Session Factory (Priority: P2)

**Goal**: `compiler-worker` and `generator-api` `import from openkb.db` and get a working async session without managing connection strings or pool settings. `ConfigurationError` raised when `DATABASE_URL` is missing. Works identically against local Docker Postgres and Azure Database for PostgreSQL Flexible Server.

**Independent Test**: Import `get_session` from `openkb.db`; execute `SELECT 1` through the session; verify success. Unset `DATABASE_URL`; verify `ConfigurationError` is raised.

### Implementation for User Story 3

- [X] T015 [US3] Implement `openkb/db/engine.py`: define `ConfigurationError(Exception)`; implement `get_engine() → AsyncEngine` — reads `DATABASE_URL` from environment (via `python-dotenv`), raises `ConfigurationError` if missing or not a valid `postgresql+asyncpg://` URL, creates singleton `AsyncEngine` with `pool_size=5`, `max_overflow=10`, `pool_pre_ping=True`; implement `get_session() → AsyncContextManager[AsyncSession]` — commits on clean exit, rolls back on exception, closes session on exit; implement `get_connection() → AsyncContextManager[AsyncConnection]` — yields raw `AsyncConnection` for DDL/bulk use
- [X] T016 [US3] Update `openkb/db/__init__.py` with all public exports per `contracts/db-session-factory.md`: `from openkb.db.engine import get_engine, get_session, get_connection, ConfigurationError`; `from openkb.db.metadata import metadata, knowledge_bases, documents, wiki_pages`; add `__all__` list

### Tests for User Story 3

- [X] T017 [P] [US3] Write `tests/db/test_factory.py`: test `get_engine()` returns same singleton on repeated calls; test `get_engine()` raises `ConfigurationError` when `DATABASE_URL` is unset (use `monkeypatch.delenv`); test `get_session()` commits on clean exit (insert a row, verify it persists after context exit); test `get_session()` rolls back on unhandled exception (insert a row, raise inside block, verify row absent); test `get_connection()` returns working connection; test `pool_pre_ping=True` is configured on the engine

**Checkpoint**: US3 independently testable — `from openkb.db import get_session` works; `uv run pytest tests/db/test_factory.py -v` passes.

---

## Phase 6: User Story 4 — Schema Is Forward-Compatible with Phase 1 (Priority: P2)

**Goal**: A Phase 1 migration adding `org_id` (nullable UUID) to `knowledge_bases` and `added_by` (nullable UUID) to `documents` applies cleanly on top of Phase 0 with seed data present — no data loss, no errors.

**Independent Test**: Apply Phase 0 schema + seed data; run stub Phase 1 migration; verify `org_id` and `added_by` columns exist, existing rows have NULL for new columns, row counts unchanged.

### Tests for User Story 4

- [X] T018 [US4] Write `tests/db/test_forward_compat.py`: author an inline stub Alembic revision `0002_stub_phase1_add_org_id_added_by` that executes `ALTER TABLE knowledge_bases ADD COLUMN org_id UUID NULL` and `ALTER TABLE documents ADD COLUMN added_by UUID NULL`; using `seeded_db` fixture, run the stub migration via `alembic upgrade`; assert both new columns exist with correct type and nullability; assert original row counts in all three tables are unchanged; assert existing rows have NULL for the new columns; assert the stub migration is listed in `alembic history` with a label distinct from Phase 0 migration (SC-006 verification)

**Checkpoint**: US4 independently testable — `uv run pytest tests/db/test_forward_compat.py -v` passes.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Ensure the feature is complete, integrated, and discoverable.

- [X] T019 [P] Verify `pyproject.toml` `dev` optional-dependency group includes the new `db` group (or add `openkb[db]` as a dev dependency) so `uv sync --extra dev` installs all runtime + test dependencies; confirm `alembic`, `sqlalchemy[asyncio]`, and `asyncpg` are reachable after sync
- [X] T020 [P] Ensure `.gitignore` excludes `.env` (not `.env.example`); add `pgdata/` and `*.pyc` entries if not already present
- [X] T021 Update `openkb/db/migrations/script.py.mako` template to include the `from __future__ import annotations` header and a `# Phase: X` comment placeholder consistent with the naming convention in `research.md` Decision 2

---

## Dependency Graph

```
US1 (Schema on fresh DB)
  └─ requires: Phase 1 (T001–T005) + Phase 2 (T006)
  └─ blocks:   US2, US3, US4

US2 (Local dev in one step)
  └─ requires: US1 complete (migration must exist to run)
  └─ blocks:   manual dev workflow

US3 (Shared session factory)
  └─ requires: Phase 2 (T006 — metadata.py)
  └─ blocks:   compiler-worker and generator-api integration tests

US4 (Forward compatibility)
  └─ requires: US1 complete (Phase 0 schema must exist), US3 (seeded_db fixture)
  └─ blocks:   Phase 1 architecture sign-off
```

## Parallel Execution Opportunities

After Phase 2 (T006) is complete, the following can run in parallel:

| Parallel Track A (US1) | Parallel Track B (US2) | Parallel Track C (US3) |
|------------------------|------------------------|------------------------|
| T007 (alembic env.py)  | T011 (docker-compose)  | T015 (engine.py)       |
| T008 (migration file)  | T012 (.env.example)    | T016 (__init__.py)     |
| T009 (conftest.py)     | T013 (db_seed.py)      | T017 (test_factory)    |
| T010 (test_migrations) | T014 (test_seed)       |                        |

US4 (T018) can begin as soon as US1 and the `seeded_db` fixture (T009) are complete.

## Implementation Strategy

**MVP scope**: US1 + US2 (Phases 1–4). Delivers a fully usable development database from a single `docker compose up --wait`. This is the minimum required to unblock `compiler-worker` and `generator-api` teams.

**Increment 2**: US3 (Phase 5). Delivers the importable session factory — unblocks integration testing across services.

**Increment 3**: US4 (Phase 6) + Polish (Phase 7). Validates forward compatibility and closes out the feature.

---

## Summary

| Metric | Count |
|--------|-------|
| Total tasks | 21 |
| Phase 1 (Setup) | 5 |
| Phase 2 (Foundational) | 1 |
| Phase 3 (US1 — Schema) | 4 |
| Phase 4 (US2 — Local dev) | 4 |
| Phase 5 (US3 — Session factory) | 3 |
| Phase 6 (US4 — Forward compat) | 1 |
| Phase 7 (Polish) | 3 |
| Parallelisable [P] tasks | 12 |
| User story coverage | 4/4 (US1–US4) |
