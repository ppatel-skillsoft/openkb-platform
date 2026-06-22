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
import uuid
from dataclasses import dataclass, field
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
KB_A_WIKI_PAGE_SUMMARY_ID = "aaaaaaaa-0002-0000-0000-000000000001"
KB_A_WIKI_PAGE_CONCEPT_ID = "aaaaaaaa-0003-0000-0000-000000000001"
KB_A_SLUG = "kb-a"
KB_A_PREFIX = f"kb-{KB_A_ID}"
KB_A_WIKI_PREFIX = f"{KB_A_PREFIX}/wiki"
KB_A_TOPIC_KEYWORDS = frozenset(
    ["main sequence", "red giant", "hertzsprung-russell", "planetary nebula", "stellar"]
)

KB_B_ID = "bbbbbbbb-0000-0000-0000-000000000002"
KB_B_DOC_ID = "bbbbbbbb-0001-0000-0000-000000000002"
KB_B_WIKI_PAGE_SUMMARY_ID = "bbbbbbbb-0002-0000-0000-000000000002"
KB_B_WIKI_PAGE_CONCEPT_ID = "bbbbbbbb-0003-0000-0000-000000000002"
KB_B_SLUG = "kb-b"
KB_B_PREFIX = f"kb-{KB_B_ID}"
KB_B_WIKI_PREFIX = f"{KB_B_PREFIX}/wiki"
KB_B_TOPIC_KEYWORDS = frozenset(
    ["chloroplast", "photosynthesis", "stomata", "xylem", "phloem", "calvin cycle"]
)

AZURITE_CONTAINER = "openkb"

# Pre-compiled wiki blobs seeded into Azurite so query tests work without
# triggering the compiler-worker.
KB_A_BLOBS: dict[str, str] = {
    f"{KB_A_WIKI_PREFIX}/summary.md": """\
# Astronomy Introduction — Summary

This document introduces stellar classification and planetary formation.
Key topics: main sequence stars, red giants, the Hertzsprung-Russell diagram,
planetary nebula, and stellar evolution cycles.

Source: astronomy-intro.md
""",
    f"{KB_A_WIKI_PREFIX}/concepts/stellar-classification.md": """\
# Stellar Classification

Stars are classified by temperature and luminosity on the Hertzsprung-Russell diagram.
Main sequence stars fuse hydrogen in their cores. Red giants form when main sequence
stars exhaust their hydrogen supply and expand. A planetary nebula is the expelled
outer shell of a red giant after it collapses to a white dwarf.

Source: astronomy-intro.md
""",
    f"{KB_A_PREFIX}/raw/astronomy-intro.md": (
        Path(__file__).parent / "fixtures" / "kb_a" / "astronomy-intro.md"
    ).read_text(),
}

KB_B_BLOBS: dict[str, str] = {
    f"{KB_B_WIKI_PREFIX}/summary.md": """\
# Botany Introduction — Summary

This document introduces plant cell biology and energy production.
Key topics: chloroplasts, photosynthesis, stomata, xylem and phloem transport,
and the Calvin cycle.

Source: botany-intro.md
""",
    f"{KB_B_WIKI_PREFIX}/concepts/photosynthesis.md": """\
# Photosynthesis

Photosynthesis is the process by which plants convert light energy into chemical energy.
Chloroplasts contain chlorophyll, which absorbs sunlight. Carbon dioxide enters leaves
through stomata. Water and nutrients are transported via xylem; sugars are distributed
via phloem. The Calvin cycle converts CO2 into glucose in the chloroplast stroma.

Source: botany-intro.md
""",
    f"{KB_B_PREFIX}/raw/botany-intro.md": (
        Path(__file__).parent / "fixtures" / "kb_b" / "botany-intro.md"
    ).read_text(),
}


# ---------------------------------------------------------------------------
# Invariant assertions (run before any test)
# ---------------------------------------------------------------------------

def _assert_fixture_invariants() -> None:
    """Fail-fast guard: topic keywords must be disjoint to detect cross-contamination."""
    assert KB_A_TOPIC_KEYWORDS.isdisjoint(KB_B_TOPIC_KEYWORDS), (
        "KB fixture topic keywords must be disjoint for cross-contamination to be detectable"
    )
    assert KB_A_PREFIX != KB_B_PREFIX, "Storage path prefixes must be unique"
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
    ts = "2026-06-21T00:00:00+00:00"

    # knowledge_bases
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
        f"{KB_A_WIKI_PREFIX}", False,
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
        f"{KB_B_WIKI_PREFIX}", False,
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
        f"azurite://{AZURITE_CONTAINER}/{KB_A_PREFIX}/raw/astronomy-intro.md",
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
        f"azurite://{AZURITE_CONTAINER}/{KB_B_PREFIX}/raw/botany-intro.md",
        "botany-intro.md", "complete", None, False, 115, ts, ts, None,
    )

    # wiki_pages — KB-A
    await conn.execute(
        """
        INSERT INTO wiki_pages
            (id, kb_id, page_type, slug, blob_path, entity_type, last_compiled_at,
             created_at, updated_at, deleted_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (kb_id, slug) DO NOTHING
        """,
        KB_A_WIKI_PAGE_SUMMARY_ID, KB_A_ID, "summary", "summary",
        f"{KB_A_WIKI_PREFIX}/summary.md", None, ts, ts, ts, None,
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
        f"{KB_A_WIKI_PREFIX}/concepts/stellar-classification.md", None, ts, ts, ts, None,
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
        f"{KB_B_WIKI_PREFIX}/summary.md", None, ts, ts, ts, None,
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
        f"{KB_B_WIKI_PREFIX}/concepts/photosynthesis.md", None, ts, ts, ts, None,
    )


async def _teardown_postgres(conn: asyncpg.Connection) -> None:
    for kb_id in (KB_A_ID, KB_B_ID):
        await conn.execute("DELETE FROM wiki_pages WHERE kb_id = $1", kb_id)
        await conn.execute("DELETE FROM compiler_jobs WHERE kb_id = $1", kb_id)
        await conn.execute("DELETE FROM documents WHERE kb_id = $1", kb_id)
        await conn.execute("DELETE FROM knowledge_bases WHERE id = $1", kb_id)


# ---------------------------------------------------------------------------
# Session fixture
# ---------------------------------------------------------------------------

@dataclass
class IsolationFixtures:
    """Container for session-level fixture state shared across all test modules."""

    database_url: str
    blob_connection_string: str
    azure_container: str
    generator_api_url: str
    scratch_root: Path

    kb_a_id: str = KB_A_ID
    kb_b_id: str = KB_B_ID
    kb_a_doc_id: str = KB_A_DOC_ID
    kb_b_doc_id: str = KB_B_DOC_ID
    kb_a_topic_keywords: frozenset[str] = field(default_factory=lambda: KB_A_TOPIC_KEYWORDS)
    kb_b_topic_keywords: frozenset[str] = field(default_factory=lambda: KB_B_TOPIC_KEYWORDS)
    kb_a_wiki_prefix: str = KB_A_WIKI_PREFIX
    kb_b_wiki_prefix: str = KB_B_WIKI_PREFIX


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
    container = os.environ.get("AZURE_KB_CONTAINER", AZURITE_CONTAINER)
    generator_url = _require_env("GENERATOR_API_URL")
    scratch_str = os.environ.get("COMPILER_SCRATCH_ROOT", "/scratch")

    fixtures = IsolationFixtures(
        database_url=raw_db_url,
        blob_connection_string=blob_cs,
        azure_container=container,
        generator_api_url=generator_url,
        scratch_root=Path(scratch_str),
    )

    # Seed Postgres
    conn = await asyncpg.connect(db_url)
    try:
        await _seed_postgres(conn)
    finally:
        await conn.close()

    # Seed Azurite blobs
    await seed_blobs(blob_cs, container, KB_A_BLOBS)
    await seed_blobs(blob_cs, container, KB_B_BLOBS)

    yield fixtures

    # Teardown
    conn = await asyncpg.connect(db_url)
    try:
        await _teardown_postgres(conn)
    finally:
        await conn.close()

    await delete_kb_blobs(blob_cs, container, KB_A_PREFIX)
    await delete_kb_blobs(blob_cs, container, KB_B_PREFIX)


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
