from __future__ import annotations

"""pytest-asyncio fixtures for tests/db/.

Fixtures:
    db_engine   — AsyncEngine connected to the test database.
    connection  — AsyncConnection with a SAVEPOINT for test isolation.
    session     — AsyncSession bound to the savepoint connection.
    seeded_db   — connection + seed data inserted before the test.

All fixtures require a running Postgres 15 instance reachable via the
DATABASE_URL environment variable.  Start one with:

    docker compose up postgres migrate --wait

For CI set DATABASE_URL to the test database URL (include ?ssl=false for
containers without TLS configured).
"""

import os

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from openkb.db.metadata import documents, knowledge_bases

load_dotenv()


@pytest_asyncio.fixture
async def db_engine():
    """Create an AsyncEngine per test (function-scoped for loop-safety)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        pytest.skip("DATABASE_URL not set — skipping DB tests")
    from openkb.db.engine import _extract_ssl_connect_args
    url, connect_args = _extract_ssl_connect_args(url)
    engine = create_async_engine(url, echo=False, connect_args=connect_args)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def connection(db_engine):
    """Yield an AsyncConnection wrapped in a SAVEPOINT for test isolation.

    Each test gets a fresh savepoint; the outer transaction is rolled back
    after the test so no state leaks between tests.
    """
    async with db_engine.begin() as conn:
        async with conn.begin_nested() as nested:
            yield conn
            await nested.rollback()


@pytest_asyncio.fixture
async def session(connection):
    """Yield an AsyncSession bound to the test savepoint connection."""
    async with AsyncSession(connection, expire_on_commit=False) as s:
        yield s


@pytest_asyncio.fixture
async def seeded_db(connection):
    """Insert seed fixture rows then yield the connection.

    Seed data mirrors scripts/db_seed.py but is injected inline so tests
    do not depend on the seed script being installed.
    """
    await connection.execute(
        insert(knowledge_bases).values(
            name="Scratch KB",
            slug="scratch-kb",
            status="active",
            git_versioning_enabled=True,
            compilation_config={
                "language": "en",
                "pageindex_threshold": 0.5,
                "entity_types": ["person", "organization"],
                "extra_headers": {},
            },
        )
    )
    kb_row = (
        await connection.execute(
            text("SELECT id FROM knowledge_bases WHERE slug = 'scratch-kb'")
        )
    ).fetchone()
    kb_id = kb_row[0]

    await connection.execute(
        insert(documents).values(
            kb_id=kb_id,
            source_type="pdf",
            source_uri="blob://scratch-kb/sample.pdf",
            original_filename="sample.pdf",
            status="complete",
        )
    )
    await connection.execute(
        insert(documents).values(
            kb_id=kb_id,
            source_type="url",
            source_uri="https://example.com/docs",
            status="pending",
        )
    )
    yield connection
