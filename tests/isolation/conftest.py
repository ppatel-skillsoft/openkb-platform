"""Session-scoped fixtures for sidecar isolation tests.

Responsibilities
----------------
1. Assert fixture-invariant disjointness before any test runs.
2. Seed Postgres (knowledge_bases, documents, wiki_pages) with KB-A and KB-B rows.
3. Seed Azurite with pre-compiled wiki blobs for both KBs.
4. Expose a helper to enqueue a compiler_jobs row so tests can trigger real
   compilation jobs.
5. Tear down all seeded data after the test session.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio

from tests.isolation.helpers.blob_helpers import delete_kb_blobs, seed_blobs

# ---------------------------------------------------------------------------
# Fixture metadata
# ---------------------------------------------------------------------------

KB_A_ID = "aaaaaaaa-0000-0000-0000-000000000001"
KB_A_DOC_ID = "aaaaaaaa-0001-0000-0000-000000000001"
KB_A_COMPILE_DOC_ID = "aaaaaaaa-0004-0000-0000-000000000001"  # used only for compilation tests
KB_A_WIKI_PAGE_SUMMARY_ID = "aaaaaaaa-0002-0000-0000-000000000001"
KB_A_WIKI_PAGE_CONCEPT_ID = "aaaaaaaa-0003-0000-0000-000000000001"
KB_A_SLUG = "kb-a"
KB_A_CONTAINER = f"kb-{KB_A_ID}"
KB_A_TOPIC_KEYWORDS = frozenset(
    ["main sequence", "red giant", "hertzsprung", "planetary nebula", "stellar"]
)

KB_B_ID = "bbbbbbbb-0000-0000-0000-000000000002"
KB_B_DOC_ID = "bbbbbbbb-0001-0000-0000-000000000002"
KB_B_COMPILE_DOC_ID = "bbbbbbbb-0004-0000-0000-000000000002"  # used only for compilation tests
KB_B_WIKI_PAGE_SUMMARY_ID = "bbbbbbbb-0002-0000-0000-000000000002"
KB_B_WIKI_PAGE_CONCEPT_ID = "bbbbbbbb-0003-0000-0000-000000000002"
KB_B_SLUG = "kb-b"
KB_B_CONTAINER = f"kb-{KB_B_ID}"
KB_B_TOPIC_KEYWORDS = frozenset(
    ["chloroplast", "photosynthesis", "stomata", "xylem", "phloem", "calvin cycle"]
)

# Pre-compiled wiki blobs seeded into per-KB Azurite containers so query tests
# work without triggering the compiler-worker.
# Container for KB-A: KB_A_CONTAINER ("kb-aaaaaaaa-...")
# Blob names within the container: "wiki/summary.md", "wiki/concepts/...", "raw/..."
_FIXTURE_DIR = Path(__file__).parent / "fixtures"

KB_A_BLOBS: dict[str, str] = {
    "wiki/summary.md": """\
# Astronomy Introduction — Summary

This document introduces stellar classification and planetary formation.
Key topics: main sequence stars, red giants, the Hertzsprung-Russell diagram,
planetary nebula, and stellar evolution cycles.

Source: astronomy-intro.md
""",
    "wiki/concepts/stellar-classification.md": """\
# Stellar Classification

Stars are classified by temperature and luminosity on the Hertzsprung-Russell diagram.
Main sequence stars fuse hydrogen in their cores. Red giants form when main sequence
stars exhaust their hydrogen supply and expand. A planetary nebula is the expelled
outer shell of a red giant after it collapses to a white dwarf.

Source: astronomy-intro.md
""",
    # Raw source blob for compilation tests
    "raw/astronomy-intro.md": (_FIXTURE_DIR / "kb_a" / "astronomy-intro.md").read_text(),
}

KB_B_BLOBS: dict[str, str] = {
    "wiki/summary.md": """\
# Botany Introduction — Summary

This document introduces plant cell biology and energy production.
Key topics: chloroplasts, photosynthesis, stomata, xylem and phloem transport,
and the Calvin cycle.

Source: botany-intro.md
""",
    "wiki/concepts/photosynthesis.md": """\
# Photosynthesis

Photosynthesis is the process by which plants convert light energy into chemical energy.
Chloroplasts contain chlorophyll, which absorbs sunlight. Carbon dioxide enters leaves
through stomata. Water and nutrients are transported via xylem; sugars are distributed
via phloem. The Calvin cycle converts CO2 into glucose in the chloroplast stroma.

Source: botany-intro.md
""",
    # Raw source blob for compilation tests
    "raw/botany-intro.md": (_FIXTURE_DIR / "kb_b" / "botany-intro.md").read_text(),
}


# ---------------------------------------------------------------------------
# Invariant assertions (run before any test)
# ---------------------------------------------------------------------------

def _assert_fixture_invariants() -> None:
    """Fail-fast guard: topic keywords must be disjoint to detect cross-contamination."""
    assert KB_A_TOPIC_KEYWORDS.isdisjoint(KB_B_TOPIC_KEYWORDS), (
        "KB fixture topic keywords must be disjoint for cross-contamination to be detectable"
    )
    assert KB_A_CONTAINER != KB_B_CONTAINER, "Storage containers must be unique"
    assert KB_A_SLUG != KB_B_SLUG, "KB slugs must be unique"


_assert_fixture_invariants()


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise EnvironmentError(f"Required env var {name!r} not set for isolation tests")
    return v


# ---------------------------------------------------------------------------
# Async DB helpers
# ---------------------------------------------------------------------------

async def _seed_postgres(conn: asyncpg.Connection) -> None:
    ts = datetime(2026, 6, 21, 0, 0, 0, tzinfo=timezone.utc)

    # knowledge_bases — storage_container_path=None means router uses "kb-{id}" convention
    await conn.execute(
        """
        INSERT INTO knowledge_bases
            (id, name, slug, description, storage_container_path,
             git_versioning_enabled, compilation_config, status, created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (id) DO NOTHING
        """,
        KB_A_ID, "Isolation Test KB-A: Astronomy", KB_A_SLUG,
        "Test fixture for sidecar isolation validation — astronomy content",
        None, False,
        json.dumps({"language": "en"}), "active", ts, ts, None,
    )
    await conn.execute(
        """
        INSERT INTO knowledge_bases
            (id, name, slug, description, storage_container_path,
             git_versioning_enabled, compilation_config, status, created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT (id) DO NOTHING
        """,
        KB_B_ID, "Isolation Test KB-B: Botany", KB_B_SLUG,
        "Test fixture for sidecar isolation validation — botany content",
        None, False,
        json.dumps({"language": "en"}), "active", ts, ts, None,
    )

    # documents
    await conn.execute(
        """
        INSERT INTO documents
            (id, kb_id, source_type, source_uri, original_filename,
             status, failure_reason, pageindex_used, token_cost, created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (id) DO NOTHING
        """,
        KB_A_DOC_ID, KB_A_ID, "markdown",
        f"azurite://{KB_A_CONTAINER}/raw/astronomy-intro.md",
        "astronomy-intro.md", "complete", None, False, 120, ts, ts, None,
    )
    await conn.execute(
        """
        INSERT INTO documents
            (id, kb_id, source_type, source_uri, original_filename,
             status, failure_reason, pageindex_used, token_cost, created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (id) DO NOTHING
        """,
        KB_B_DOC_ID, KB_B_ID, "markdown",
        f"azurite://{KB_B_CONTAINER}/raw/botany-intro.md",
        "botany-intro.md", "complete", None, False, 115, ts, ts, None,
    )

    # Compile-only documents — separate from query docs so compilation status
    # changes don't affect the pre-seeded 'complete' documents used by query tests
    await conn.execute(
        """
        INSERT INTO documents
            (id, kb_id, source_type, source_uri, original_filename,
             status, failure_reason, pageindex_used, token_cost, created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (id) DO NOTHING
        """,
        KB_A_COMPILE_DOC_ID, KB_A_ID, "markdown",
        f"azurite://{KB_A_CONTAINER}/raw/astronomy-intro.md",
        "astronomy-intro.md", "pending", None, False, 0, ts, ts, None,
    )
    await conn.execute(
        """
        INSERT INTO documents
            (id, kb_id, source_type, source_uri, original_filename,
             status, failure_reason, pageindex_used, token_cost, created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (id) DO NOTHING
        """,
        KB_B_COMPILE_DOC_ID, KB_B_ID, "markdown",
        f"azurite://{KB_B_CONTAINER}/raw/botany-intro.md",
        "botany-intro.md", "pending", None, False, 0, ts, ts, None,
    )

    # wiki_pages — KB-A (blob_path uses "{container}/{blob_name}" format)
    await conn.execute(
        """
        INSERT INTO wiki_pages
            (id, kb_id, page_type, slug, blob_path, entity_type, last_compiled_at,
             created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (kb_id, slug) DO NOTHING
        """,
        KB_A_WIKI_PAGE_SUMMARY_ID, KB_A_ID, "summary", "summary",
        f"{KB_A_CONTAINER}/wiki/summary.md", None, ts, ts, ts, None,
    )
    await conn.execute(
        """
        INSERT INTO wiki_pages
            (id, kb_id, page_type, slug, blob_path, entity_type, last_compiled_at,
             created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (kb_id, slug) DO NOTHING
        """,
        KB_A_WIKI_PAGE_CONCEPT_ID, KB_A_ID, "concept", "stellar-classification",
        f"{KB_A_CONTAINER}/wiki/concepts/stellar-classification.md", None, ts, ts, ts, None,
    )

    # wiki_pages — KB-B
    await conn.execute(
        """
        INSERT INTO wiki_pages
            (id, kb_id, page_type, slug, blob_path, entity_type, last_compiled_at,
             created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (kb_id, slug) DO NOTHING
        """,
        KB_B_WIKI_PAGE_SUMMARY_ID, KB_B_ID, "summary", "summary",
        f"{KB_B_CONTAINER}/wiki/summary.md", None, ts, ts, ts, None,
    )
    await conn.execute(
        """
        INSERT INTO wiki_pages
            (id, kb_id, page_type, slug, blob_path, entity_type, last_compiled_at,
             created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (kb_id, slug) DO NOTHING
        """,
        KB_B_WIKI_PAGE_CONCEPT_ID, KB_B_ID, "concept", "photosynthesis",
        f"{KB_B_CONTAINER}/wiki/concepts/photosynthesis.md", None, ts, ts, ts, None,
    )


async def _teardown_postgres(conn: asyncpg.Connection) -> None:
    # Delete all child records for both KBs before removing parents.
    # wiki_pages is deleted last (just before knowledge_bases) to avoid FK
    # violations from compiler-worker inserting new rows after the first delete.
    kb_ids = [KB_A_ID, KB_B_ID]
    await conn.execute("DELETE FROM compiler_jobs WHERE kb_id = ANY($1::uuid[])", kb_ids)
    await conn.execute("DELETE FROM documents WHERE kb_id = ANY($1::uuid[])", kb_ids)
    await conn.execute("DELETE FROM wiki_pages WHERE kb_id = ANY($1::uuid[])", kb_ids)
    for kb_id in kb_ids:
        await conn.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)


# ---------------------------------------------------------------------------
# Session fixture
# ---------------------------------------------------------------------------

@dataclass
class IsolationFixtures:
    """Container for session-level fixture state shared across all test modules."""

    database_url: str
    blob_connection_string: str
    generator_api_url: str
    scratch_root: Path

    kb_a_id: str = KB_A_ID
    kb_b_id: str = KB_B_ID
    kb_a_doc_id: str = KB_A_DOC_ID
    kb_b_doc_id: str = KB_B_DOC_ID
    kb_a_compile_doc_id: str = KB_A_COMPILE_DOC_ID
    kb_b_compile_doc_id: str = KB_B_COMPILE_DOC_ID
    kb_a_topic_keywords: frozenset[str] = field(default_factory=lambda: KB_A_TOPIC_KEYWORDS)
    kb_b_topic_keywords: frozenset[str] = field(default_factory=lambda: KB_B_TOPIC_KEYWORDS)


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy for pytest-asyncio session scope."""
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def isolation_fixtures() -> AsyncGenerator[IsolationFixtures, None]:
    """Session-scoped fixture: seed DB + Azurite, yield state, then teardown."""
    # Resolve required env vars
    raw_db_url = _require_env("DATABASE_URL")
    # asyncpg uses postgresql:// not postgresql+asyncpg://
    db_url = raw_db_url.replace("postgresql+asyncpg://", "postgresql://")
    blob_cs = _require_env("AZURE_STORAGE_CONNECTION_STRING")
    generator_url = _require_env("GENERATOR_API_URL")
    scratch_str = os.environ.get("COMPILER_SCRATCH_ROOT", "/scratch")

    fixtures = IsolationFixtures(
        database_url=raw_db_url,
        blob_connection_string=blob_cs,
        generator_api_url=generator_url,
        scratch_root=Path(scratch_str),
    )

    # Seed Postgres
    conn = await asyncpg.connect(db_url)
    try:
        await _seed_postgres(conn)
    finally:
        await conn.close()

    # Seed Azurite blobs into per-KB containers (matching "kb-{uuid}" convention)
    await seed_blobs(blob_cs, KB_A_CONTAINER, KB_A_BLOBS)
    await seed_blobs(blob_cs, KB_B_CONTAINER, KB_B_BLOBS)

    yield fixtures

    # Brief pause to allow any in-flight compiler jobs to reach terminal status
    # before we begin removing rows that those jobs may still reference.
    await asyncio.sleep(3)

    # Teardown
    conn = await asyncpg.connect(db_url)
    try:
        await _teardown_postgres(conn)
    finally:
        await conn.close()

    await delete_kb_blobs(blob_cs, KB_A_CONTAINER, "wiki/")
    await delete_kb_blobs(blob_cs, KB_B_CONTAINER, "wiki/")


async def enqueue_job(
    database_url: str,
    kb_id: str,
    doc_id: str,
    blob_path: str,
    filename: str,
) -> str:
    """Insert a row into compiler_jobs and return its job id."""
    raw_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(raw_url)
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO compiler_jobs (kb_id, document_id, blob_path, filename)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            kb_id, doc_id, blob_path, filename,
        )
        return str(row["id"])
    finally:
        await conn.close()


async def wait_for_job_completion(
    database_url: str,
    doc_id: str,
    *,
    timeout: float = 120.0,
    interval: float = 2.0,
) -> str:
    """Poll documents.status until it is 'complete' or 'failed'."""
    import asyncio
    import time

    raw_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn = await asyncpg.connect(raw_url)
        try:
            row = await conn.fetchrow(
                "SELECT status FROM documents WHERE id = $1", doc_id
            )
        finally:
            await conn.close()

        if row and row["status"] in ("complete", "failed"):
            return row["status"]
        await asyncio.sleep(interval)

    raise TimeoutError(
        f"Document {doc_id} did not reach terminal status within {timeout}s"
    )
