# Research: Phase 0 Postgres Schema Bootstrap

**Phase**: 0 — Research & Decisions
**Branch**: `002-phase0-postgres-schema`
**Date**: 2026-06-21
**Status**: Complete — all NEEDS CLARIFICATION resolved

---

## Decision 1 — Async Database Driver: SQLAlchemy Core 2.x + asyncpg

**Decision**: Use SQLAlchemy Core 2.x with the `asyncpg` driver, via `create_async_engine` and `AsyncSession`/`AsyncConnection`.

**Rationale**:
- **Lightweight** — SQLAlchemy Core uses Table/Column/MetaData directly without ORM model classes; fits the spec requirement for "lightweight — no heavy ORM"
- **Async-native** — `create_async_engine("postgresql+asyncpg://...")` works identically in pytest-asyncio tests and in production async services; no sync/async impedance mismatch
- **Single interface for both local and Azure Postgres** — the only difference is the `DATABASE_URL` value; no code changes required (FR-013)
- **Ecosystem maturity** — SQLAlchemy 2.x is the de-facto Python database layer; `asyncpg` is the fastest pure-Python async Postgres driver (benchmarks consistently show 3–5× throughput over psycopg2 for async workloads)
- **pytest-asyncio compatibility** — the `dev` extras in `pyproject.toml` already include `pytest-asyncio==1.3.0`; async engine integrates directly

**Alternatives considered**:
- *Raw asyncpg* — more direct but no Table definitions, no expression builder, harder to maintain schema migrations alongside the driver. Rejected: adds complexity without removing any.
- *SQLAlchemy ORM (mapped classes)* — adds declarative models, relationships, lazy loading; heavier than needed for a schema-bootstrap + connection-factory task. Rejected: spec explicitly says "lightweight — no heavy ORM".
- *psycopg3 (psycopg[async])* — newer driver with a similar interface; less mature ecosystem for asyncio specifically; `asyncpg` has broader adoption and better-tested SQLAlchemy integration at this time. Revisit for Phase 1+.

**New dependencies** (to be added to `pyproject.toml`):
```
sqlalchemy==2.0.x   # Core 2.x with async support
asyncpg==0.30.x     # PostgreSQL async driver
alembic==1.14.x     # Migrations (see Decision 2)
python-dotenv==1.2.2  # already present — used for .env loading
```

---

## Decision 2 — Migration Tool: Alembic with asyncio runner

**Decision**: Alembic with `run_async_migrations` pattern (asyncio runner in `env.py`).

**Rationale**:
- Python-native, integrates directly with SQLAlchemy's MetaData; `alembic revision --autogenerate` can diff against the live DB
- Versioned, ordered migration files with a migration history table (`alembic_version`) — satisfies FR-007 (migrations are incremental and idempotent)
- The asyncio runner (`asyncio.run(run_async_migrations())` in `env.py`) allows migrations to reuse the same async engine as the application, avoiding a synchronous dependency
- Widely understood by Python backend engineers; low onboarding friction

**Naming convention**: migration files prefixed with a zero-padded sequence and phase label — e.g., `0001_phase0_initial_schema.py` — so Phase 0 and Phase 1 migrations are visually distinct in `alembic history` (SC-002, User Story 4 acceptance scenario 2).

**Alternatives considered**:
- *Flyway / Liquibase* — JVM-based; incompatible with a Python-only project; introduces a JVM runtime dependency. Rejected.
- *Raw SQL scripts with a custom runner* — no state tracking, no autogenerate, no rollback support. Rejected.
- *Yoyo-migrations* — lighter than Alembic but no SQLAlchemy integration, no autogenerate. Rejected.

---

## Decision 3 — UUID Primary Key Generation: `gen_random_uuid()`

**Decision**: All PK columns use `server_default=text("gen_random_uuid()")` in SQLAlchemy Table definitions; the Postgres function `gen_random_uuid()` generates V4 UUIDs at insert time.

**Rationale**:
- `gen_random_uuid()` is built into Postgres 13+ (no extension required); Postgres 15 is the target (FR-008) so this is unconditional
- Server-side generation means application code never needs to supply an ID on INSERT — simplifies compiler-worker and generator-api inserts
- V4 UUID (random) has negligible collision probability; no ordering/sequential assumptions in the schema
- Consistent with `research/02-data-model.md`: "All primary keys are UUIDs (`gen_random_uuid()`)"

**Alternatives considered**:
- *`uuid_generate_v4()` from `uuid-ossp` extension* — requires enabling the extension explicitly; unnecessary on Postgres 13+. Rejected.
- *Application-generated UUIDs (Python `uuid.uuid4()`)* — workable but requires the application to supply the ID on every INSERT; makes bulk inserts and seed scripts slightly more verbose. The server-default approach is simpler and consistent across all callers.
- *ULIDs or UUIDv7 (monotonic)* — better index locality for high-write tables; overkill for Phase 0 scale; revisit in Phase 1 if insert performance becomes a concern.

---

## Decision 4 — `compilation_config` Column Type: JSONB

**Decision**: `compilation_config` on `knowledge_bases` is a `JSONB` column (not `JSON` or `TEXT`).

**Rationale**:
- `JSONB` stores binary-parsed JSON — supports GIN indexing, `->` / `->>` path operators, and `@>` containment queries natively in Postgres
- The shape from `research/02-data-model.md` is `{ language, pageindex_threshold, entity_types, extra_headers }` — matches OpenKB's `config.yaml` structure; application layer owns schema validation (spec assumption)
- The `->` operator returning NULL for missing keys (not an error) satisfies the edge-case requirement in the spec
- No application-level JSON serialization/deserialization required; SQLAlchemy's `JSONB` type handles Python dict ↔ Postgres JSONB automatically

**Alternatives considered**:
- *`JSON` type* — text storage, no binary indexing, slower for queries. No meaningful advantage over JSONB for this use case. Rejected.
- *`TEXT` with application parsing* — loses Postgres-native query capabilities; inconsistent with `research/02-data-model.md`. Rejected.
- *Separate columns per config key* — inflexible; adding a new config key requires a migration. Rejected.

---

## Decision 5 — `status` Column Strategy: TEXT (no DB-level ENUM)

**Decision**: Both `knowledge_bases.status` (`active`, `archived`) and `documents.status` (`pending`, `compiling`, `complete`, `failed`) are `TEXT NOT NULL` columns. No Postgres ENUM types.

**Rationale**:
- Adding a new status value to a Postgres ENUM requires `ALTER TYPE ... ADD VALUE`, which (before Postgres 12) couldn't be done inside a transaction, and even in Postgres 15 cannot be rolled back. This creates migration friction when Phase 1 extends the domain.
- Application-layer validation enforces the allowed values — consistent with the spec's stated assumption and with `research/02-data-model.md`
- A CHECK constraint (`CHECK (status IN ('active', 'archived'))`) could be added later as an additive migration if desired without any downtime

**Alternatives considered**:
- *Postgres ENUM type* — enforces values at DB level but is painful to extend via migrations. Rejected per spec assumption.
- *CHECK constraint now* — adds a constraint that would need to be dropped and recreated to extend in Phase 1. Deferred to Phase 1 when the value set is more stable.

---

## Decision 6 — Docker Compose Setup

**Decision**: `docker-compose.yml` at the repository root using Compose v2 syntax (`services:` top-level, no `version:` key). Two services: `postgres` and `migrate`.

**`postgres` service**:
- Image: `postgres:15-alpine` (matches Azure Database for PostgreSQL Flexible Server 15; alpine for minimal image size)
- Named volume `pgdata` for persistence across restarts (satisfies User Story 2 acceptance scenario 2)
- Health check: `pg_isready -U ${POSTGRES_USER}` with `interval: 5s`, `retries: 10` — ensures the `migrate` service only starts after Postgres is truly accepting connections
- Env vars from `.env` file (`.env.example` committed, `.env` gitignored)

**`migrate` service**:
- Runs `alembic upgrade head` against the `postgres` service on startup
- `depends_on: postgres: condition: service_healthy` — guarantees ordering
- `restart: on-failure` — retries if Postgres isn't ready despite health check (belt-and-suspenders)

**Seed** is intentionally a separate command (`python scripts/db_seed.py`), not baked into `docker-compose.yml` — satisfies FR-011 (seed is independently runnable).

**Alternatives considered**:
- *Baking migrations into the Postgres image entrypoint* — couples migration code to the image; harder to iterate. Rejected.
- *Makefile targets wrapping docker compose* — useful addition but optional; can be added in Phase 1 without blocking this feature.

---

## Decision 7 — Seed/Fixture Mechanism: Standalone Python Script

**Decision**: `scripts/db_seed.py` — a standalone Python script that imports `openkb.db.engine` and inserts fixture data using the same session factory as the application.

**Seed data**:
- 1 × `knowledge_bases` row: `id` generated by Postgres, `name = "Scratch KB"`, `slug = "scratch-kb"`, `status = "active"`, `git_versioning_enabled = True`, `compilation_config = {"language": "en", "pageindex_threshold": 0.5, "entity_types": ["person", "organization"], "extra_headers": {}}`
- 2 × `documents` rows: one PDF (`source_type = "pdf"`) with `status = "complete"`, one URL (`source_type = "url"`) with `status = "pending"` — realistic enough for `compiler-worker` and `generator-api` integration tests

**Idempotency**: The seed script uses `INSERT ... ON CONFLICT (slug) DO NOTHING` for `knowledge_bases` and checks for existing `kb_id` + `source_uri` before inserting documents — ensures running it twice is safe without requiring a clean database (edge case in spec).

**Alternatives considered**:
- *Alembic data migration* — couples fixture data to migration history; seed would re-run on every `alembic upgrade head`. Rejected (FR-011 requires independent runnability).
- *pytest fixtures only* — not runnable from the command line for manual dev use. Rejected.
- *Separate `fixtures/` module* — overly complex for Phase 0; a single `scripts/db_seed.py` suffices.

---

## Decision 8 — Environment Variable: `DATABASE_URL`

**Decision**: Single `DATABASE_URL` environment variable in SQLAlchemy async URL format:
- **Local dev**: `postgresql+asyncpg://openkb:openkb@localhost:5432/openkb`
- **Production**: `postgresql+asyncpg://openkb:<password>@<hostname>:5432/openkb?ssl=require`

**Rationale**:
- Single variable is simpler to document, rotate, and inject via Azure Container Apps secrets / Key Vault references
- The `?ssl=require` suffix handles Azure Postgres's TLS requirement without any code changes (FR-013)
- `python-dotenv` (already in `pyproject.toml`) loads `.env` automatically in development; production uses actual environment variables set at container runtime
- No credentials ever appear in code or in committed files (FR-012)

**Connection pool defaults** (SQLAlchemy `create_async_engine`):
- `pool_size=5`, `max_overflow=10`, `pool_pre_ping=True` — reasonable defaults for Phase 0 single-service usage; configurable via additional env vars in Phase 1

**Alternatives considered**:
- *Separate `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` vars* — more explicit but requires assembly code in `engine.py`; `DATABASE_URL` is the standard for SQLAlchemy projects. Rejected.
- *Hardwired to asyncpg URL format* — fine; `asyncpg` is the only driver in use. No need to support `psycopg2` in the same factory.

---

## Resolved: All NEEDS CLARIFICATION Items

| Item | Resolution |
|------|-----------|
| Exact Python version range | 3.10–3.13 (from `pyproject.toml`) |
| ORM vs Core | SQLAlchemy Core 2.x (Decision 1) |
| Migration tool | Alembic with asyncio runner (Decision 2) |
| UUID generation | `gen_random_uuid()` server-default (Decision 3) |
| `compilation_config` type | JSONB (Decision 4) |
| `status` enforcement | TEXT + application-layer validation (Decision 5) |
| Local dev mechanism | Docker Compose v2, postgres:15-alpine (Decision 6) |
| Seed mechanism | `scripts/db_seed.py` standalone script (Decision 7) |
| Connection string format | `DATABASE_URL` env var (Decision 8) |
| Postgres version (local vs Azure) | Postgres 15 (`postgres:15-alpine` matches Azure Flexible Server default) |
