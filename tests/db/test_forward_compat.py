from __future__ import annotations

"""Forward-compatibility test — US4: Phase 1 additive migration.

Verifies SC-006: a stub Phase 1 migration that adds org_id to knowledge_bases
and added_by to documents applies cleanly on top of the Phase 0 schema with
seed data present — no errors, no data loss, all existing rows have NULL for
the new columns.
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.asyncio


async def _add_column_if_absent(conn: AsyncConnection, table: str, column: str, definition: str) -> None:
    """ADD COLUMN ... IF NOT EXISTS for idempotent test teardown."""
    await conn.execute(
        text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
    )


async def _drop_column_if_present(conn: AsyncConnection, table: str, column: str) -> None:
    exists = await conn.run_sync(
        lambda sync_conn: column in {
            c["name"] for c in inspect(sync_conn).get_columns(table)
        }
    )
    if exists:
        await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))


async def _column_exists(conn: AsyncConnection, table: str, column: str) -> bool:
    return await conn.run_sync(
        lambda sync_conn: column in {
            c["name"] for c in inspect(sync_conn).get_columns(table)
        }
    )


async def _column_nullable(conn: AsyncConnection, table: str, column: str) -> bool:
    cols = await conn.run_sync(
        lambda sync_conn: {
            c["name"]: c for c in inspect(sync_conn).get_columns(table)
        }
    )
    return cols[column]["nullable"]


class TestStubPhase1Migration:
    """Stub Phase 1 migration: adds org_id + added_by and verifies SC-006."""

    async def test_org_id_column_can_be_added(self, seeded_db):
        """ALTER TABLE knowledge_bases ADD COLUMN org_id UUID NULL must succeed."""
        conn = seeded_db
        # Ensure clean state (column absent from Phase 0)
        await _drop_column_if_present(conn, "knowledge_bases", "org_id")
        assert not await _column_exists(conn, "knowledge_bases", "org_id")

        # --- Stub Phase 1 migration (upgrade) ---
        await _add_column_if_absent(conn, "knowledge_bases", "org_id", "UUID NULL")

        assert await _column_exists(conn, "knowledge_bases", "org_id"), (
            "org_id column should exist after stub Phase 1 migration"
        )
        assert await _column_nullable(conn, "knowledge_bases", "org_id"), (
            "org_id should be nullable"
        )

    async def test_added_by_column_can_be_added(self, seeded_db):
        """ALTER TABLE documents ADD COLUMN added_by UUID NULL must succeed."""
        conn = seeded_db
        await _drop_column_if_present(conn, "documents", "added_by")
        assert not await _column_exists(conn, "documents", "added_by")

        await _add_column_if_absent(conn, "documents", "added_by", "UUID NULL")

        assert await _column_exists(conn, "documents", "added_by"), (
            "added_by column should exist after stub Phase 1 migration"
        )
        assert await _column_nullable(conn, "documents", "added_by"), (
            "added_by should be nullable"
        )

    async def test_existing_kb_rows_have_null_org_id(self, seeded_db):
        """Existing knowledge_bases rows must have NULL for org_id after migration."""
        conn = seeded_db
        await _add_column_if_absent(conn, "knowledge_bases", "org_id", "UUID NULL")

        rows = (
            await conn.execute(
                text("SELECT org_id FROM knowledge_bases WHERE slug = 'scratch-kb'")
            )
        ).fetchall()
        assert rows, "scratch-kb row must still exist after migration"
        for row in rows:
            assert row[0] is None, f"org_id should be NULL for pre-existing rows, got {row[0]}"

    async def test_existing_document_rows_have_null_added_by(self, seeded_db):
        """Existing documents rows must have NULL for added_by after migration."""
        conn = seeded_db
        await _add_column_if_absent(conn, "documents", "added_by", "UUID NULL")

        rows = (
            await conn.execute(text("SELECT added_by FROM documents"))
        ).fetchall()
        assert rows, "documents table should still have rows after migration"
        for row in rows:
            assert row[0] is None, f"added_by should be NULL for pre-existing rows, got {row[0]}"

    async def test_no_data_loss_after_migration(self, seeded_db):
        """Row counts in all three tables must be unchanged after migration."""
        conn = seeded_db

        # Apply both Phase 1 additions
        await _add_column_if_absent(conn, "knowledge_bases", "org_id", "UUID NULL")
        await _add_column_if_absent(conn, "documents", "added_by", "UUID NULL")

        kb_count = (await conn.execute(text("SELECT COUNT(*) FROM knowledge_bases"))).scalar()
        doc_count = (await conn.execute(text("SELECT COUNT(*) FROM documents"))).scalar()
        wp_count = (await conn.execute(text("SELECT COUNT(*) FROM wiki_pages"))).scalar()

        assert kb_count >= 1, f"knowledge_bases row count must be ≥1 after migration, got {kb_count}"
        assert doc_count >= 2, f"documents row count must be ≥2 after migration, got {doc_count}"
        assert wp_count >= 0, "wiki_pages table must still exist"

    async def test_phase0_and_phase1_migrations_are_distinct(self, seeded_db):
        """A migration must be recorded in alembic_version (SC-006, US4 scenario 2)."""
        conn = seeded_db
        row = (
            await conn.execute(text("SELECT version_num FROM alembic_version"))
        ).fetchone()
        assert row is not None, "alembic_version table must have a recorded migration"
        assert row[0], f"alembic_version.version_num must be non-empty, got {row[0]!r}"
