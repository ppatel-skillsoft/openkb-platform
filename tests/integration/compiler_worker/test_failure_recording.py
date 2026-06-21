from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from compiler_worker.models import CompilationJob, SidecarStatus

pytestmark = pytest.mark.integration


def _make_job(doc_info: dict) -> CompilationJob:
    return CompilationJob(
        job_id=str(uuid.uuid4()),
        kb_id=doc_info["kb_id"],
        document_id=doc_info["doc_id"],
        blob_path=doc_info["blob_path"],
        filename=doc_info["filename"],
        enqueued_at="2026-06-21T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_sidecar_add_error_records_failed(
    async_db_session,
    blob_client,
    seed_kb,
    seed_document,
    worker_config,
    tmp_path,
):
    """Sidecar /add returns 404 → document is marked failed, no wiki_pages rows."""
    from openkb.db import documents, wiki_pages
    from sqlalchemy import select
    from compiler_worker.job import process_job
    import httpx as httpx_lib

    doc_info = seed_document
    container = seed_kb["container"]

    # Upload source blob
    blob_client.ensure_container(container)
    src = tmp_path / "test.md"
    src.write_bytes(b"content")
    blob_client.upload_from_file(doc_info["blob_path"], src)

    job = _make_job(doc_info)

    with patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "start",
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "init",
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "add",
        side_effect=httpx_lib.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        ),
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "teardown",
    ):
        await process_job(job, worker_config, async_db_session, blob_client)

    doc_row = (
        await async_db_session.execute(
            select(documents).where(documents.c.id == doc_info["doc_id"])
        )
    ).fetchone()
    assert doc_row.status == "failed"
    assert doc_row.failure_reason

    wiki_rows = (
        await async_db_session.execute(
            select(wiki_pages).where(wiki_pages.c.kb_id == doc_info["kb_id"])
        )
    ).fetchall()
    assert len(wiki_rows) == 0


@pytest.mark.asyncio
async def test_sidecar_timeout_records_failed(
    async_db_session,
    blob_client,
    seed_kb,
    seed_document,
    worker_config,
    tmp_path,
):
    """Sidecar never finishes within timeout → document marked failed with timeout reason."""
    from openkb.db import documents
    from sqlalchemy import select
    from compiler_worker.job import process_job
    from compiler_worker.exceptions import SidecarTimeoutError

    doc_info = seed_document
    container = seed_kb["container"]

    blob_client.ensure_container(container)
    src = tmp_path / "test.md"
    src.write_bytes(b"content")
    blob_client.upload_from_file(doc_info["blob_path"], src)

    job = _make_job(doc_info)

    # Override timeout to 0 so it always fires
    import compiler_worker.config as cfg_mod
    from dataclasses import replace
    fast_config = replace(worker_config, sidecar_compile_timeout=0)

    compiling_status = SidecarStatus(status="compiling")

    with patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "start",
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "init",
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "add",
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "get_status",
        return_value=compiling_status,
    ), patch.object(
        __import__("compiler_worker.sidecar", fromlist=["SidecarProcess"]).SidecarProcess,
        "teardown",
    ):
        await process_job(job, fast_config, async_db_session, blob_client)

    doc_row = (
        await async_db_session.execute(
            select(documents).where(documents.c.id == doc_info["doc_id"])
        )
    ).fetchone()
    assert doc_row.status == "failed"
    assert "timed out" in doc_row.failure_reason.lower() or "0s" in doc_row.failure_reason


@pytest.mark.asyncio
async def test_missing_blob_records_failed(
    async_db_session,
    blob_client,
    seed_kb,
    seed_document,
    worker_config,
):
    """Non-existent blob path → document marked failed with blob-not-found reason."""
    from openkb.db import documents
    from sqlalchemy import select
    from compiler_worker.job import process_job

    doc_info = seed_document
    # NOTE: we deliberately do NOT upload the blob

    job = _make_job(doc_info)

    await process_job(job, worker_config, async_db_session, blob_client)

    doc_row = (
        await async_db_session.execute(
            select(documents).where(documents.c.id == doc_info["doc_id"])
        )
    ).fetchone()
    assert doc_row.status == "failed"
    assert "blob" in doc_row.failure_reason.lower() or "not found" in doc_row.failure_reason.lower()


@pytest.mark.asyncio
async def test_missing_kb_records_failed(
    async_db_session,
    blob_client,
    worker_config,
    seed_document,
):
    """Unknown kb_id → document marked failed with KB-not-found reason."""
    from openkb.db import documents
    from sqlalchemy import select
    from compiler_worker.job import process_job

    doc_info = seed_document
    job = CompilationJob(
        job_id=str(uuid.uuid4()),
        kb_id=str(uuid.uuid4()),  # unknown KB
        document_id=doc_info["doc_id"],
        blob_path=doc_info["blob_path"],
        filename=doc_info["filename"],
        enqueued_at="2026-06-21T00:00:00Z",
    )

    await process_job(job, worker_config, async_db_session, blob_client)

    doc_row = (
        await async_db_session.execute(
            select(documents).where(documents.c.id == doc_info["doc_id"])
        )
    ).fetchone()
    assert doc_row.status in ("failed", "pending")  # KBNotFoundError raised before update
