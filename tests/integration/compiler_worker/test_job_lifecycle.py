from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from compiler_worker.models import CompilationJob, SidecarPage, SidecarStatus

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_happy_path_end_to_end(
    async_db_session,
    blob_client,
    seed_kb,
    seed_document,
    worker_config,
    tmp_path,
):
    """Upload a real blob to Azurite, mock sidecar HTTP, verify DB + blob outcomes."""
    from openkb.db import documents, wiki_pages
    from sqlalchemy import select
    from compiler_worker.job import process_job

    doc_info = seed_document
    kb_id = doc_info["kb_id"]
    doc_id = doc_info["doc_id"]
    blob_path = doc_info["blob_path"]
    filename = doc_info["filename"]
    container = seed_kb["container"]

    # Upload a real source document to Azurite
    blob_client.ensure_container(container)
    raw_content = b"# Test Document\n\nHello world."
    mock_src = tmp_path / "test-doc.md"
    mock_src.write_bytes(raw_content)
    blob_client.upload_from_file(blob_path, mock_src)

    # Two mock pages the sidecar will "produce"
    page1_content = b"# Summary\n\nThis is a summary."
    page2_content = b"# Concept\n\nThis is a concept."
    page1_file = tmp_path / "wiki" / "summaries" / "test-doc.md"
    page2_file = tmp_path / "wiki" / "concepts" / "test-concept.md"
    page1_file.parent.mkdir(parents=True)
    page2_file.parent.mkdir(parents=True)
    page1_file.write_bytes(page1_content)
    page2_file.write_bytes(page2_content)

    mock_status_complete = SidecarStatus(
        status="complete",
        pages=[
            SidecarPage(
                slug="summaries/test-doc",
                page_type="summary",
                entity_type=None,
                file_path="wiki/summaries/test-doc.md",
            ),
            SidecarPage(
                slug="concepts/test-concept",
                page_type="concept",
                entity_type=None,
                file_path="wiki/concepts/test-concept.md",
            ),
        ],
        token_cost=1234,
        pageindex_used=False,
        error=None,
    )

    job = CompilationJob(
        job_id=str(uuid.uuid4()),
        kb_id=kb_id,
        document_id=doc_id,
        blob_path=blob_path,
        filename=filename,
        enqueued_at="2026-06-21T00:00:00Z",
    )

    def mock_start(config, scratch_dir):
        # Copy mock page files into the scratch wiki directory
        (scratch_dir / "wiki" / "summaries").mkdir(parents=True, exist_ok=True)
        (scratch_dir / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)
        (scratch_dir / "wiki" / "summaries" / "test-doc.md").write_bytes(page1_content)
        (scratch_dir / "wiki" / "concepts" / "test-concept.md").write_bytes(page2_content)

    with patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "start",
        side_effect=mock_start,
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "init",
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "add",
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "get_status",
        return_value=mock_status_complete,
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "teardown",
    ):
        await process_job(job, worker_config, async_db_session, blob_client)

    # Verify document status
    doc_row = (
        await async_db_session.execute(
            select(documents).where(documents.c.id == doc_id)
        )
    ).fetchone()
    assert doc_row.status == "complete"
    assert doc_row.token_cost == 1234
    assert doc_row.pageindex_used is False

    # Verify wiki_pages rows
    wiki_rows = (
        await async_db_session.execute(
            select(wiki_pages).where(wiki_pages.c.kb_id == kb_id)
        )
    ).fetchall()
    slugs = {row.slug for row in wiki_rows}
    assert "summaries/test-doc" in slugs
    assert "concepts/test-concept" in slugs

    # Verify wiki blobs in Azurite
    import io
    for slug in ["summaries/test-doc", "concepts/test-concept"]:
        wiki_blob_path = f"{container}/wiki/{slug}.md"
        dest = tmp_path / f"verify_{slug.replace('/', '_')}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob_client.download_to_file(wiki_blob_path, dest)
        assert dest.exists()
        assert dest.stat().st_size > 0
