from __future__ import annotations

"""Schema validation tests — US1: Schema Applied to a Fresh Database.

Validates that the Phase 0 migration created every table, column, type,
nullability, constraint, and index exactly as specified in data-model.md
(SC-002).  Also verifies idempotency: running `alembic upgrade head` twice
produces no error and no schema change (User Story 1, acceptance scenario 2).
"""

import subprocess
import sys

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def get_columns(conn: AsyncConnection, table_name: str) -> dict:
    """Return a dict of {column_name: inspector_col_dict} for a table."""
    columns = await conn.run_sync(
        lambda sync_conn: {
            c["name"]: c
            for c in inspect(sync_conn).get_columns(table_name)
        }
    )
    return columns


async def get_indexes(conn: AsyncConnection, table_name: str) -> list[dict]:
    return await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).get_indexes(table_name)
    )


async def get_unique_constraints(conn: AsyncConnection, table_name: str) -> list[dict]:
    return await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).get_unique_constraints(table_name)
    )


async def get_foreign_keys(conn: AsyncConnection, table_name: str) -> list[dict]:
    return await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).get_foreign_keys(table_name)
    )


async def table_exists(conn: AsyncConnection, table_name: str) -> bool:
    return await conn.run_sync(
        lambda sync_conn: inspect(sync_conn).has_table(table_name)
    )


# ---------------------------------------------------------------------------
# Table-existence tests
# ---------------------------------------------------------------------------


class TestTablesExist:
    async def test_knowledge_bases_exists(self, connection):
        assert await table_exists(connection, "knowledge_bases")

    async def test_documents_exists(self, connection):
        assert await table_exists(connection, "documents")

    async def test_wiki_pages_exists(self, connection):
        assert await table_exists(connection, "wiki_pages")

    async def test_alembic_version_exists(self, connection):
        assert await table_exists(connection, "alembic_version")


# ---------------------------------------------------------------------------
# knowledge_bases column tests
# ---------------------------------------------------------------------------


class TestKnowledgeBasesColumns:
    async def test_all_columns_present(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        expected = {
            "id", "name", "slug", "description", "storage_container_path",
            "git_versioning_enabled", "compilation_config", "status",
            "created_at", "updated_at", "deleted_at",
        }
        assert expected <= set(cols.keys())

    async def test_id_is_primary_key_and_not_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["id"]["nullable"] is False

    async def test_name_not_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["name"]["nullable"] is False

    async def test_slug_not_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["slug"]["nullable"] is False

    async def test_description_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["description"]["nullable"] is True

    async def test_git_versioning_enabled_not_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["git_versioning_enabled"]["nullable"] is False

    async def test_status_not_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["status"]["nullable"] is False

    async def test_created_at_not_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["created_at"]["nullable"] is False

    async def test_updated_at_not_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["updated_at"]["nullable"] is False

    async def test_deleted_at_nullable(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        assert cols["deleted_at"]["nullable"] is True

    async def test_slug_unique_constraint(self, connection):
        constraints = await get_unique_constraints(connection, "knowledge_bases")
        slugs = [c for c in constraints if "slug" in c["column_names"]]
        assert slugs, "Expected UNIQUE constraint on knowledge_bases.slug"

    async def test_compilation_config_is_jsonb(self, connection):
        cols = await get_columns(connection, "knowledge_bases")
        type_str = str(cols["compilation_config"]["type"]).upper()
        assert "JSONB" in type_str


# ---------------------------------------------------------------------------
# documents column tests
# ---------------------------------------------------------------------------


class TestDocumentsColumns:
    async def test_all_columns_present(self, connection):
        cols = await get_columns(connection, "documents")
        expected = {
            "id", "kb_id", "source_type", "source_uri", "original_filename",
            "status", "failure_reason", "pageindex_used", "token_cost",
            "created_at", "updated_at", "deleted_at",
        }
        assert expected <= set(cols.keys())

    async def test_kb_id_not_nullable(self, connection):
        cols = await get_columns(connection, "documents")
        assert cols["kb_id"]["nullable"] is False

    async def test_source_type_not_nullable(self, connection):
        cols = await get_columns(connection, "documents")
        assert cols["source_type"]["nullable"] is False

    async def test_status_not_nullable(self, connection):
        cols = await get_columns(connection, "documents")
        assert cols["status"]["nullable"] is False

    async def test_failure_reason_nullable(self, connection):
        cols = await get_columns(connection, "documents")
        assert cols["failure_reason"]["nullable"] is True

    async def test_token_cost_nullable(self, connection):
        cols = await get_columns(connection, "documents")
        assert cols["token_cost"]["nullable"] is True

    async def test_deleted_at_nullable(self, connection):
        cols = await get_columns(connection, "documents")
        assert cols["deleted_at"]["nullable"] is True

    async def test_kb_id_foreign_key(self, connection):
        fks = await get_foreign_keys(connection, "documents")
        kb_fks = [f for f in fks if "kb_id" in f["constrained_columns"]]
        assert kb_fks, "Expected FK documents.kb_id → knowledge_bases.id"
        assert kb_fks[0]["referred_table"] == "knowledge_bases"
        assert kb_fks[0]["referred_columns"] == ["id"]

    async def test_kb_id_index_exists(self, connection):
        indexes = await get_indexes(connection, "documents")
        names = [i["name"] for i in indexes]
        assert "ix_documents_kb_id" in names


# ---------------------------------------------------------------------------
# wiki_pages column tests
# ---------------------------------------------------------------------------


class TestWikiPagesColumns:
    async def test_all_columns_present(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        expected = {
            "id", "kb_id", "page_type", "slug", "blob_path",
            "entity_type", "last_compiled_at",
            "created_at", "updated_at", "deleted_at",
        }
        assert expected <= set(cols.keys())

    async def test_kb_id_not_nullable(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        assert cols["kb_id"]["nullable"] is False

    async def test_page_type_not_nullable(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        assert cols["page_type"]["nullable"] is False

    async def test_slug_not_nullable(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        assert cols["slug"]["nullable"] is False

    async def test_blob_path_nullable(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        assert cols["blob_path"]["nullable"] is True

    async def test_entity_type_nullable(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        assert cols["entity_type"]["nullable"] is True

    async def test_last_compiled_at_nullable(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        assert cols["last_compiled_at"]["nullable"] is True

    async def test_deleted_at_nullable(self, connection):
        cols = await get_columns(connection, "wiki_pages")
        assert cols["deleted_at"]["nullable"] is True

    async def test_kb_id_foreign_key(self, connection):
        fks = await get_foreign_keys(connection, "wiki_pages")
        kb_fks = [f for f in fks if "kb_id" in f["constrained_columns"]]
        assert kb_fks, "Expected FK wiki_pages.kb_id → knowledge_bases.id"
        assert kb_fks[0]["referred_table"] == "knowledge_bases"

    async def test_kb_id_index_exists(self, connection):
        indexes = await get_indexes(connection, "wiki_pages")
        names = [i["name"] for i in indexes]
        assert "ix_wiki_pages_kb_id" in names

    async def test_composite_unique_kb_id_slug(self, connection):
        constraints = await get_unique_constraints(connection, "wiki_pages")
        composite = [
            c for c in constraints
            if set(c["column_names"]) == {"kb_id", "slug"}
        ]
        assert composite, "Expected UNIQUE(kb_id, slug) on wiki_pages"
        assert composite[0]["name"] == "uq_wiki_pages_kb_id_slug"


# ---------------------------------------------------------------------------
# Idempotency test (SC-003)
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    def test_alembic_upgrade_head_is_idempotent(self, tmp_path):
        """Running alembic upgrade head twice must not error (SC-003)."""
        import os
        from pathlib import Path
        repo_root = str(Path(__file__).parent.parent.parent)
        env = {**os.environ}  # inherits DATABASE_URL with ssl=false
        result1 = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=repo_root,
        )
        assert result1.returncode == 0, (
            f"First alembic upgrade head failed:\n{result1.stderr}"
        )
        result2 = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            env=env,
            cwd=repo_root,
        )
        assert result2.returncode == 0, (
            f"Second alembic upgrade head failed (not idempotent):\n{result2.stderr}"
        )
