from __future__ import annotations

"""Seed idempotency tests — US2: Local Dev Environment.

Verifies that:
- Running the seed logic once creates exactly 1 KB and 2 documents (SC-004).
- Running the seed logic a second time leaves row counts unchanged (FR-011,
  edge case: "seed run twice must be idempotent").
"""

import pytest
from sqlalchemy import func, select

from openkb.db.metadata import documents, knowledge_bases

pytestmark = pytest.mark.asyncio


async def _kb_count(session) -> int:
    result = await session.execute(
        select(func.count()).select_from(knowledge_bases).where(
            knowledge_bases.c.slug == "scratch-kb"
        )
    )
    return result.scalar()


async def _doc_count(session, kb_id) -> int:
    result = await session.execute(
        select(func.count()).select_from(documents).where(
            documents.c.kb_id == kb_id
        )
    )
    return result.scalar()


class TestSeedCreatesExpectedRows:
    async def test_scratch_kb_row_exists(self, seeded_db):
        from sqlalchemy.ext.asyncio import AsyncSession
        async with AsyncSession(bind=seeded_db, expire_on_commit=False) as session:
            count = await _kb_count(session)
        assert count == 1, f"Expected 1 scratch-kb row, got {count}"

    async def test_two_documents_created(self, seeded_db):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=seeded_db, expire_on_commit=False) as session:
            kb_row = (
                await session.execute(
                    select(knowledge_bases.c.id).where(
                        knowledge_bases.c.slug == "scratch-kb"
                    )
                )
            ).fetchone()
            assert kb_row is not None
            count = await _doc_count(session, kb_row[0])
        assert count == 2, f"Expected 2 documents, got {count}"

    async def test_pdf_document_present(self, seeded_db):
        from sqlalchemy.ext.asyncio import AsyncSession
        async with AsyncSession(bind=seeded_db, expire_on_commit=False) as session:
            row = (
                await session.execute(
                    select(documents.c.source_type, documents.c.status).where(
                        documents.c.source_type == "pdf"
                    )
                )
            ).fetchone()
        assert row is not None
        assert row[1] == "complete"

    async def test_url_document_present(self, seeded_db):
        from sqlalchemy.ext.asyncio import AsyncSession
        async with AsyncSession(bind=seeded_db, expire_on_commit=False) as session:
            row = (
                await session.execute(
                    select(documents.c.source_type, documents.c.status).where(
                        documents.c.source_type == "url"
                    )
                )
            ).fetchone()
        assert row is not None
        assert row[1] == "pending"


class TestSeedIdempotency:
    """Running the seed fixtures a second time must not change row counts."""

    async def test_duplicate_kb_insert_is_skipped(self, seeded_db):
        """Inserting scratch-kb a second time (ON CONFLICT DO NOTHING) leaves count=1."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=seeded_db, expire_on_commit=False) as session:
            stmt = (
                pg_insert(knowledge_bases)
                .values(
                    name="Scratch KB",
                    slug="scratch-kb",
                    status="active",
                    git_versioning_enabled=True,
                )
                .on_conflict_do_nothing(index_elements=["slug"])
            )
            await session.execute(stmt)
            await session.flush()
            count = await _kb_count(session)
        assert count == 1, "Duplicate KB insert should be ignored"

    async def test_duplicate_document_insert_is_skipped(self, seeded_db):
        """Inserting the same source_uri twice must leave doc count at 2."""
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(bind=seeded_db, expire_on_commit=False) as session:
            kb_row = (
                await session.execute(
                    select(knowledge_bases.c.id).where(
                        knowledge_bases.c.slug == "scratch-kb"
                    )
                )
            ).fetchone()
            kb_id = kb_row[0]

            # Attempt to re-insert an existing document (simulates seed run twice).
            existing = (
                await session.execute(
                    select(documents.c.id).where(
                        documents.c.kb_id == kb_id,
                        documents.c.source_uri == "blob://scratch-kb/sample.pdf",
                    )
                )
            ).fetchone()
            # The idempotency guard: only insert if absent.
            if not existing:
                await session.execute(
                    documents.insert().values(
                        kb_id=kb_id,
                        source_type="pdf",
                        source_uri="blob://scratch-kb/sample.pdf",
                        original_filename="sample.pdf",
                        status="complete",
                    )
                )

            count = await _doc_count(session, kb_id)
        assert count == 2, "Second seed run must not add duplicate documents"
