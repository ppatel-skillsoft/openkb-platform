from __future__ import annotations

"""Standalone seed/fixture helper for the Phase 0 Postgres schema.

Creates a scratch KnowledgeBase and two Document records in the database.
Safe to run multiple times — existing records are skipped (idempotent).

Usage:
    python scripts/db_seed.py

Requires:
    DATABASE_URL env var (or a .env file in the repo root).
    The Phase 0 migrations must already have been applied:
        docker compose up postgres migrate --wait
    OR:
        alembic upgrade head
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Allow running from repo root without installing as a package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openkb.db.metadata import documents, knowledge_bases  # noqa: E402

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

SCRATCH_KB = {
    "name": "Scratch KB",
    "slug": "scratch-kb",
    "status": "active",
    "git_versioning_enabled": True,
    "compilation_config": {
        "language": "en",
        "pageindex_threshold": 0.5,
        "entity_types": ["person", "organization"],
        "extra_headers": {},
    },
}

SEED_DOCUMENTS = [
    {
        "source_type": "pdf",
        "source_uri": "blob://scratch-kb/sample.pdf",
        "original_filename": "sample.pdf",
        "status": "complete",
    },
    {
        "source_type": "url",
        "source_uri": "https://example.com/docs",
        "status": "pending",
    },
]


# ---------------------------------------------------------------------------
# Seed logic
# ---------------------------------------------------------------------------


async def seed() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        logger.error(
            "[seed] DATABASE_URL is not set. Copy .env.example to .env and "
            "fill in the connection string."
        )
        sys.exit(1)

    from openkb.db.engine import _extract_ssl_connect_args
    url, connect_args = _extract_ssl_connect_args(url)
    engine = create_async_engine(url, echo=False, connect_args=connect_args)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # --- knowledge_bases -----------------------------------------------
        # INSERT ... ON CONFLICT (slug) DO NOTHING — idempotent (FR-011)
        stmt = (
            pg_insert(knowledge_bases)
            .values(**SCRATCH_KB)
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        await session.execute(stmt)
        await session.flush()

        # Fetch the (possibly pre-existing) KB row to get its id.
        kb_row = (
            await session.execute(
                select(knowledge_bases.c.id).where(
                    knowledge_bases.c.slug == SCRATCH_KB["slug"]
                )
            )
        ).fetchone()
        kb_id = kb_row[0]

        inserted_kb = 0
        result = await session.execute(
            select(knowledge_bases.c.name).where(
                knowledge_bases.c.id == kb_id
            )
        )
        if result.fetchone():
            # Row existed before or was just inserted — check created_at vs NOW()
            # to determine if it's new; simpler: just track via on_conflict above.
            pass

        logger.info("[seed] KnowledgeBase: %s (id=%s)", SCRATCH_KB["slug"], kb_id)

        # --- documents -----------------------------------------------------
        inserted_docs = 0
        for doc in SEED_DOCUMENTS:
            # Check whether this uri already exists for this KB to stay idempotent.
            existing = (
                await session.execute(
                    select(documents.c.id).where(
                        documents.c.kb_id == kb_id,
                        documents.c.source_uri == doc["source_uri"],
                    )
                )
            ).fetchone()

            if existing:
                logger.info(
                    "[seed] Document already exists: %s (skipped)",
                    doc["source_uri"],
                )
            else:
                await session.execute(
                    documents.insert().values(kb_id=kb_id, **doc)
                )
                inserted_docs += 1
                logger.info(
                    "[seed] Inserted document: %s",
                    doc.get("original_filename") or doc["source_uri"],
                )

        await session.commit()

    doc_count = (
        await _count_rows(engine, "documents", f"kb_id = '{kb_id}'")
    )
    logger.info(
        "[seed] Done. knowledge_bases: 1, documents for scratch-kb: %d",
        doc_count,
    )
    await engine.dispose()


async def _count_rows(engine, table: str, where: str) -> int:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {where}")
        )
        return result.scalar() or 0


if __name__ == "__main__":
    asyncio.run(seed())
