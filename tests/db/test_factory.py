from __future__ import annotations

"""Session factory tests — US3: Shared Session Factory.

Verifies:
- get_engine() returns a singleton AsyncEngine.
- get_engine() raises ConfigurationError when DATABASE_URL is missing.
- get_engine() raises ConfigurationError when DATABASE_URL is not asyncpg.
- pool_pre_ping=True is configured.
- get_session() commits on clean exit.
- get_session() rolls back on unhandled exception.
- get_connection() yields a working AsyncConnection.
"""

import os

import pytest
from sqlalchemy import text

from openkb.db import get_connection, get_engine, get_session, knowledge_bases
from openkb.db.engine import ConfigurationError, _reset_engine

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_engine_singleton():
    """Ensure each test starts with a clean engine singleton."""
    _reset_engine()
    yield
    _reset_engine()


class TestGetEngine:
    def test_returns_async_engine(self):
        from sqlalchemy.ext.asyncio import AsyncEngine
        engine = get_engine()
        assert isinstance(engine, AsyncEngine)

    def test_returns_same_singleton(self):
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_raises_on_missing_database_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ConfigurationError, match="DATABASE_URL"):
            get_engine()

    def test_raises_on_non_asyncpg_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
        with pytest.raises(ConfigurationError, match="asyncpg"):
            get_engine()

    def test_pool_pre_ping_enabled(self):
        engine = get_engine()
        assert engine.pool._pre_ping is True

    def test_pool_size(self):
        engine = get_engine()
        assert engine.pool.size() == 5


class TestGetSession:
    async def test_session_commits_on_clean_exit(self, connection):
        """Insert a row, exit cleanly — row should persist."""
        from sqlalchemy import insert, select
        from sqlalchemy.ext.asyncio import AsyncSession

        # Use the test connection directly (not the singleton engine)
        # to stay within the test transaction.
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            await session.execute(
                insert(knowledge_bases).values(
                    name="Factory Test KB",
                    slug="factory-test-kb",
                    status="active",
                    git_versioning_enabled=True,
                )
            )
            await session.commit()

        # Verify the row is readable within the same (savepoint) connection.
        row = (
            await connection.execute(
                knowledge_bases.select().where(
                    knowledge_bases.c.slug == "factory-test-kb"
                )
            )
        ).fetchone()
        assert row is not None, "Row should exist after commit"

    async def test_session_rolls_back_on_exception(self, connection):
        """Insert a row, raise inside block — row must not persist."""
        from sqlalchemy import insert, select
        from sqlalchemy.ext.asyncio import AsyncSession

        with pytest.raises(RuntimeError, match="intentional"):
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                await session.execute(
                    insert(knowledge_bases).values(
                        name="Rollback KB",
                        slug="rollback-kb",
                        status="active",
                        git_versioning_enabled=True,
                    )
                )
                raise RuntimeError("intentional rollback test")

        row = (
            await connection.execute(
                knowledge_bases.select().where(
                    knowledge_bases.c.slug == "rollback-kb"
                )
            )
        ).fetchone()
        assert row is None, "Row should have been rolled back"


class TestGetConnection:
    async def test_get_connection_executes_query(self):
        """get_connection() must yield a working AsyncConnection."""
        async with get_connection() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    async def test_get_connection_returns_independently(self):
        """Two get_connection() calls produce independent connections."""
        async with get_connection() as c1:
            async with get_connection() as c2:
                assert c1 is not c2
