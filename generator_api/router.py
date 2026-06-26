from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from generator_api.blob import BlobSyncError, rebuild_index_md, sync_wiki_tree
from generator_api.config import get_settings
from generator_api.db import get_db
from generator_api.exceptions import KBNotFoundError, KBNotReadyError
from generator_api.models import QueryRequest, QueryResponse
from generator_api.sidecar import SidecarProcess, SidecarStartError, SidecarQueryError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/kbs/{kb_id}/query", response_model=QueryResponse)
async def query_kb(
    kb_id: uuid.UUID,
    body: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Answer a natural-language question against a compiled knowledge base."""
    settings = get_settings()
    t_start = time.monotonic()
    status_code = 200

    # Path-traversal guard — FastAPI's UUID type already rejects non-UUIDs;
    # additionally ensure no special characters after str conversion.
    kb_id_str = str(kb_id)
    if not all(c in "0123456789abcdef-" for c in kb_id_str):
        return JSONResponse(status_code=422, content={"detail": "Invalid kb_id"})

    # ── DB pre-flight ────────────────────────────────────────────────────────

    row = (
        await db.execute(
            text(
                "SELECT id, slug, storage_container_path FROM knowledge_bases "
                "WHERE id = :kb_id AND deleted_at IS NULL"
            ),
            {"kb_id": kb_id_str},
        )
    ).one_or_none()
    if row is None:
        raise KBNotFoundError(kb_id_str)

    kb_slug: str = row.slug
    # Derive container from storage_container_path or fall back to kb-{id}
    storage_container_path: str | None = row.storage_container_path
    container = storage_container_path or f"kb-{kb_id_str}"

    count_row = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM documents "
                "WHERE kb_id = :kb_id AND status = 'complete' AND deleted_at IS NULL"
            ),
            {"kb_id": kb_id_str},
        )
    ).one()
    if count_row[0] == 0:
        raise KBNotReadyError(kb_id_str)

    # ── Per-request scratch directory ─────────────────────────────────────────

    request_id = str(uuid.uuid4())
    scratch_dir = settings.scratch_dir_root / request_id / "kbs"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    sidecar = SidecarProcess()
    try:
        # ── Blob sync ────────────────────────────────────────────────────────
        await sync_wiki_tree(
            connection_string=settings.azure_storage_connection_string,
            container=container,
            kb_blob_prefix="wiki/",
            scratch_dir=scratch_dir / kb_slug,
        )
        # Rebuild the aggregate index.md from all synced pages; each compiler
        # job writes a per-job index that only reflects its own session.
        rebuild_index_md(scratch_dir / kb_slug / "wiki")

        # ── Sidecar lifecycle ────────────────────────────────────────────────
        await asyncio.to_thread(
            sidecar.start,
            scratch_dir,
            kb_slug,
            settings.llm_api_key,
            settings.sidecar_startup_timeout,
        )
        await asyncio.to_thread(sidecar.init, kb_slug)

        answer, citations, tokens_used = await asyncio.wait_for(
            asyncio.to_thread(sidecar.query, kb_slug, body.question),
            timeout=settings.generator_request_timeout,
        )

        return QueryResponse(
            answer=answer, citations=citations, tokens_used=tokens_used
        )

    except (
        KBNotFoundError,
        KBNotReadyError,
        BlobSyncError,
        SidecarStartError,
        SidecarQueryError,
    ):
        status_code = 500  # will be overridden by exception handlers
        raise
    except asyncio.TimeoutError:
        status_code = 504
        raise
    except Exception:
        status_code = 500
        raise
    finally:
        await asyncio.to_thread(sidecar.teardown)
        shutil.rmtree(scratch_dir, ignore_errors=True)
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "POST /kbs/%s/query question_length=%d elapsed_ms=%d status=%d",
            kb_id_str,
            len(body.question),
            elapsed_ms,
            status_code,
        )
