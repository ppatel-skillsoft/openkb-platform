"""Route handlers for the Generator API — uses SidecarPool for persistent sidecars."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from generator_api.config import get_settings, Settings
from generator_api.db import get_db
from generator_api.exceptions import KBNotFoundError, KBNotReadyError
from generator_api.models import InvalidateRequest, QueryRequest, QueryResponse
from generator_api.service import service_delete_document
from generator_api.sidecar import SidecarQueryError, SidecarStartError

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/kbs/{kb_id}/query", response_model=QueryResponse)
async def query_kb(
    kb_id: uuid.UUID,
    body: QueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Answer a natural-language question against a compiled knowledge base.

    Routes the query to the persistent sidecar managed by SidecarPool. The
    sidecar is started on first use (cold start) and reused for subsequent
    queries (warm path — no blob sync overhead).
    """
    settings = get_settings()
    t_start = time.monotonic()
    status_code = 200

    kb_id_str = str(kb_id)

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
    container: str = row.storage_container_path or f"kb-{kb_id_str}"

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

    # ── Pool query ────────────────────────────────────────────────────────────

    pool = request.app.state.pool

    try:
        sidecar = await pool.get_or_start(kb_id_str, kb_slug, container)

        answer, citations, tokens_used = await asyncio.wait_for(
            asyncio.to_thread(sidecar.query, kb_slug, body.question),
            timeout=settings.generator_request_timeout,
        )

        pool.update_last_used(kb_id_str)
        return QueryResponse(
            answer=answer, citations=citations, tokens_used=tokens_used
        )

    except (KBNotFoundError, KBNotReadyError, SidecarStartError, SidecarQueryError):
        status_code = 500
        raise
    except asyncio.TimeoutError:
        status_code = 504
        raise
    except Exception:
        status_code = 500
        raise
    finally:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "POST /kbs/%s/query question_length=%d elapsed_ms=%d status=%d",
            kb_id_str,
            len(body.question),
            elapsed_ms,
            status_code,
        )


@router.post("/kbs/{kb_id}/invalidate", status_code=204)
async def invalidate_kb(
    kb_id: uuid.UUID,
    body: InvalidateRequest | None = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Mark the sidecar for *kb_id* stale so the next query gets fresh content.

    Called by the compiler_worker after a document compilation completes.
    The sidecar is NOT immediately restarted — it is restarted lazily on the
    next query to avoid unnecessary work when multiple documents finish quickly.

    NOTE: This endpoint has no authentication — it is network-isolated within
    the Docker Compose stack. MUST be secured before external/cloud deployment.
    """
    kb_id_str = str(kb_id)

    row = (
        await db.execute(
            text(
                "SELECT id FROM knowledge_bases WHERE id = :kb_id AND deleted_at IS NULL"
            ),
            {"kb_id": kb_id_str},
        )
    ).one_or_none()
    if row is None:
        raise KBNotFoundError(kb_id_str)

    pool = request.app.state.pool
    pool.invalidate(kb_id_str)

    doc_id = body.document_id if body else None
    logger.info("POST /kbs/%s/invalidate document_id=%s", kb_id_str, doc_id)
    return Response(status_code=204)


@router.delete("/kbs/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Remove a document from a knowledge base.

    Soft-deletes the document row, deletes its summary blob, and rebuilds
    the KB index.  No LLM calls are made.  Returns 204 on success and on
    repeat calls (idempotent).
    """
    await service_delete_document(
        kb_id=str(kb_id),
        doc_id=str(doc_id),
        db=db,
        connection_string=settings.azure_storage_connection_string,
    )


logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/kbs/{kb_id}/query", response_model=QueryResponse)
async def query_kb(
    kb_id: uuid.UUID,
    body: QueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Answer a natural-language question against a compiled knowledge base.

    Routes the query to the persistent sidecar managed by SidecarPool. The
    sidecar is started on first use (cold start) and reused for subsequent
    queries (warm path — no blob sync overhead).
    """
    settings = get_settings()
    t_start = time.monotonic()
    status_code = 200

    kb_id_str = str(kb_id)

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
    container: str = row.storage_container_path or f"kb-{kb_id_str}"

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

    # ── Pool query ────────────────────────────────────────────────────────────

    pool = request.app.state.pool

    try:
        sidecar = await pool.get_or_start(kb_id_str, kb_slug, container)

        answer, citations, tokens_used = await asyncio.wait_for(
            asyncio.to_thread(sidecar.query, kb_slug, body.question),
            timeout=settings.generator_request_timeout,
        )

        pool.update_last_used(kb_id_str)
        return QueryResponse(
            answer=answer, citations=citations, tokens_used=tokens_used
        )

    except (KBNotFoundError, KBNotReadyError, SidecarStartError, SidecarQueryError):
        status_code = 500
        raise
    except asyncio.TimeoutError:
        status_code = 504
        raise
    except Exception:
        status_code = 500
        raise
    finally:
        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        logger.info(
            "POST /kbs/%s/query question_length=%d elapsed_ms=%d status=%d",
            kb_id_str,
            len(body.question),
            elapsed_ms,
            status_code,
        )


@router.post("/kbs/{kb_id}/invalidate", status_code=204)
async def invalidate_kb(
    kb_id: uuid.UUID,
    body: InvalidateRequest | None = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Mark the sidecar for *kb_id* stale so the next query gets fresh content.

    Called by the compiler_worker after a document compilation completes.
    The sidecar is NOT immediately restarted — it is restarted lazily on the
    next query to avoid unnecessary work when multiple documents finish quickly.

    NOTE: This endpoint has no authentication — it is network-isolated within
    the Docker Compose stack. MUST be secured before external/cloud deployment.
    """
    kb_id_str = str(kb_id)

    row = (
        await db.execute(
            text(
                "SELECT id FROM knowledge_bases WHERE id = :kb_id AND deleted_at IS NULL"
            ),
            {"kb_id": kb_id_str},
        )
    ).one_or_none()
    if row is None:
        raise KBNotFoundError(kb_id_str)

    pool = request.app.state.pool
    pool.invalidate(kb_id_str)

    doc_id = body.document_id if body else None
    logger.info("POST /kbs/%s/invalidate document_id=%s", kb_id_str, doc_id)
    return Response(status_code=204)


@router.delete("/kbs/{kb_id}/documents/{doc_id}", status_code=204)
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """Remove a document from a knowledge base.

    Soft-deletes the document row, deletes its summary blob, and rebuilds
    the KB index.  No LLM calls are made.  Returns 204 on success and on
    repeat calls (idempotent).
    """
    await service_delete_document(
        kb_id=str(kb_id),
        doc_id=str(doc_id),
        db=db,
        connection_string=settings.azure_storage_connection_string,
    )
