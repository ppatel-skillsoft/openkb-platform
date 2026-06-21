# Contract: `openkb.db` — Database Session Factory

**Module**: `openkb/db/__init__.py` (public surface), `openkb/db/engine.py` (implementation)
**Branch**: `002-phase0-postgres-schema`
**Date**: 2026-06-21
**Consumers**: `compiler-worker`, `generator-api`, `scripts/db_seed.py`, `tests/db/`

---

## Purpose

`openkb.db` is the **single source of truth** for database connectivity within the OpenKB Enterprise platform. Every service that touches Postgres imports from this module — no service manages its own engine or connection string parsing.

---

## Public API

### `get_engine() → AsyncEngine`

Returns the singleton `AsyncEngine` instance. Reads `DATABASE_URL` from the environment (via `python-dotenv`) on first call; caches the engine for subsequent calls.

```python
from openkb.db import get_engine

engine = get_engine()
```

**Raises**:
- `openkb.db.ConfigurationError` — if `DATABASE_URL` is not set or cannot be parsed as a valid PostgreSQL async URL
- No exception on first call if the database is unreachable — connection errors surface at query time, not at engine creation time (SQLAlchemy lazy-connect behaviour)

---

### `get_session() → AsyncContextManager[AsyncSession]`

Async context manager that yields an `AsyncSession` bound to the singleton engine. Commits on clean exit; rolls back on exception.

```python
from openkb.db import get_session
from openkb.db.metadata import knowledge_bases
from sqlalchemy import select

async def list_active_kbs():
    async with get_session() as session:
        result = await session.execute(
            select(knowledge_bases).where(
                knowledge_bases.c.status == "active",
                knowledge_bases.c.deleted_at == None,
            )
        )
        return result.fetchall()
```

**Contract**:
- The session is committed automatically on clean context exit
- On any unhandled exception inside the `async with` block, the session is rolled back and the exception re-raised — the caller never needs to call `session.rollback()` explicitly
- The session is closed (connection returned to pool) on exit regardless of success or failure
- Thread/task safety: each `async with get_session()` call produces an independent session; do not share a session across coroutines

---

### `get_connection() → AsyncContextManager[AsyncConnection]`

Async context manager that yields a raw `AsyncConnection` for use cases requiring Core-level queries without a session (e.g., bulk COPY, DDL in tests).

```python
from openkb.db import get_connection

async def raw_query():
    async with get_connection() as conn:
        result = await conn.execute(text("SELECT NOW()"))
        return result.scalar()
```

---

### `metadata: MetaData`

The SQLAlchemy `MetaData` instance that all Table objects are registered against. Used by Alembic's `env.py` for autogenerate support.

```python
from openkb.db import metadata
```

---

### Table references (from `openkb.db.metadata`)

```python
from openkb.db.metadata import knowledge_bases, documents, wiki_pages
```

These are SQLAlchemy `Table` objects. Import them for use in `select()`, `insert()`, `update()`, `delete()` expressions.

| Export | Type | Table name |
|--------|------|-----------|
| `knowledge_bases` | `sqlalchemy.Table` | `knowledge_bases` |
| `documents` | `sqlalchemy.Table` | `documents` |
| `wiki_pages` | `sqlalchemy.Table` | `wiki_pages` |

---

### `ConfigurationError`

A custom exception raised when the module cannot initialise due to missing or invalid configuration.

```python
from openkb.db import ConfigurationError

try:
    engine = get_engine()
except ConfigurationError as e:
    logger.error("DB config missing: %s", e)
    sys.exit(1)
```

---

## Configuration

All configuration is read from the environment. In development, `python-dotenv` loads `.env` automatically.

| Environment variable | Required | Description |
|---------------------|----------|-------------|
| `DATABASE_URL` | ✅ | Full async connection URL: `postgresql+asyncpg://user:pass@host:port/db[?ssl=require]` |

**Local dev example**:
```
DATABASE_URL=postgresql+asyncpg://openkb:openkb@localhost:5432/openkb
```

**Production example** (Azure Database for PostgreSQL Flexible Server):
```
DATABASE_URL=postgresql+asyncpg://openkb:<password>@<hostname>.postgres.database.azure.com:5432/openkb?ssl=require
```

No code changes are required between environments — only the value of `DATABASE_URL` differs (FR-013).

---

## Engine defaults

| Parameter | Default | Notes |
|-----------|---------|-------|
| `pool_size` | `5` | Configurable via `DB_POOL_SIZE` env var (Phase 1) |
| `max_overflow` | `10` | Total max = 15 connections per process |
| `pool_pre_ping` | `True` | Validates connections before use; surfaces unreachable-DB errors immediately (User Story 3, acceptance scenario 2) |
| `pool_timeout` | `30` seconds | How long to wait for a free connection before raising `TimeoutError` |
| `echo` | `False` | Set `DB_ECHO=true` in `.env` to enable SQL logging for local debugging |

---

## Error handling contract

| Scenario | Behaviour | Exception type |
|----------|-----------|---------------|
| `DATABASE_URL` not set | Raised at `get_engine()` call time | `openkb.db.ConfigurationError` |
| Database unreachable at query time | Raised inside `async with get_session()` block; session rolled back | `sqlalchemy.exc.OperationalError` (wraps `asyncpg.exceptions.*`) |
| Connection pool exhausted | Raised after `pool_timeout` seconds | `sqlalchemy.exc.TimeoutError` |
| Unique constraint violation (e.g., duplicate `slug`) | Raised inside session block; session rolled back | `sqlalchemy.exc.IntegrityError` |
| Foreign key violation (e.g., invalid `kb_id`) | Raised inside session block; session rolled back | `sqlalchemy.exc.IntegrityError` |

**Principle**: The factory never swallows exceptions. All database errors propagate to the caller. The session is always cleaned up (committed or rolled back and closed) regardless of outcome.

---

## Usage pattern: compiler-worker

```python
# openkb/compiler_worker/db_writer.py
from openkb.db import get_session
from openkb.db.metadata import documents
from sqlalchemy import update

async def mark_document_complete(doc_id: str, token_cost: int) -> None:
    async with get_session() as session:
        await session.execute(
            update(documents)
            .where(documents.c.id == doc_id)
            .values(status="complete", token_cost=token_cost)
        )
        # session auto-commits on exit
```

---

## Usage pattern: generator-api

```python
# openkb/generator_api/kb_reader.py
from openkb.db import get_session
from openkb.db.metadata import knowledge_bases, wiki_pages
from sqlalchemy import select

async def get_wiki_pages(kb_id: str) -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            select(wiki_pages)
            .where(
                wiki_pages.c.kb_id == kb_id,
                wiki_pages.c.deleted_at == None,
            )
            .order_by(wiki_pages.c.slug)
        )
        return [dict(row._mapping) for row in result]
```

---

## Testing contract

Test fixtures in `tests/db/conftest.py` provide:

```python
@pytest.fixture
async def db_engine():
    """Yields an AsyncEngine pointed at the test database."""

@pytest.fixture
async def db_session(db_engine):
    """Yields an AsyncSession. Rolls back all changes after each test."""

@pytest.fixture
async def seeded_db(db_session):
    """db_session with Phase 0 seed data pre-inserted."""
```

Tests MUST use `db_session` (not `get_session()`) to get the rollback-per-test isolation guarantee. Integration tests that intentionally test the factory itself may call `get_session()` directly.

---

## Non-goals (out of scope for this contract)

- ORM mapped classes / relationship loading — use SQLAlchemy Core expressions only
- Connection pooling configuration per-service — pool defaults are shared; per-service tuning is a Phase 1 concern
- Read replicas / write-primary routing — single connection target in Phase 0
- Multi-tenancy row filtering — application layer's responsibility; the factory is tenant-agnostic
