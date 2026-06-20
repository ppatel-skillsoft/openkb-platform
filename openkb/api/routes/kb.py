from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from openkb.api.deps import Settings, get_kb_backend, get_settings
from openkb.api.models import (
    KBAddRequest,
    KBAddResponse,
    KBInitRequest,
    KBInitResponse,
    KBListResponse,
    KBQueryRequest,
    KBQueryResponse,
    KBStatusResponse,
    DocumentItem,
)
from openkb.services import (
    service_add_document,
    service_init_kb,
    service_list_kb,
    service_query_kb,
    service_status_kb,
)
from openkb.storage.base import StorageBackend

kb_router = APIRouter()

_KB_NAME_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$|^[a-z0-9]$"


@kb_router.post("/init", response_model=KBInitResponse)
async def init_kb(
    body: KBInitRequest,
    settings: Settings = Depends(get_settings),
) -> KBInitResponse:
    """Initialise a new knowledge base."""
    backend: StorageBackend = await get_kb_backend(body.kb_name, settings)
    result = await service_init_kb(backend, body.kb_name, body.model, body.language)
    return KBInitResponse(kb_name=result.kb_name, status=result.status, message=result.message)


@kb_router.post("/query", response_model=KBQueryResponse)
async def query_kb(
    body: KBQueryRequest,
    settings: Settings = Depends(get_settings),
) -> KBQueryResponse:
    """Answer a natural-language question against an existing knowledge base."""
    backend: StorageBackend = await get_kb_backend(body.kb_name, settings)
    result = await service_query_kb(backend, body.kb_name, body.question, body.save)
    return KBQueryResponse(answer=result.answer, saved_to=result.saved_to)


@kb_router.post("/add", response_model=KBAddResponse)
async def add_document(
    body: KBAddRequest,
    settings: Settings = Depends(get_settings),
) -> KBAddResponse:
    """Add a document (local file path or http/https URL) to an existing knowledge base."""
    backend: StorageBackend = await get_kb_backend(body.kb_name, settings)
    result = await service_add_document(backend, body.kb_name, body.source)
    return KBAddResponse(status=result.status, doc_name=result.doc_name, message=result.message)


@kb_router.get("/list", response_model=KBListResponse)
async def list_kb(
    kb_name: str = Query(..., pattern=_KB_NAME_PATTERN),
    settings: Settings = Depends(get_settings),
) -> KBListResponse:
    """List all documents and wiki pages in an existing knowledge base."""
    backend: StorageBackend = await get_kb_backend(kb_name, settings)
    result = await service_list_kb(backend, kb_name)
    return KBListResponse(
        documents=[DocumentItem(name=d.name, doc_name=d.doc_name, type=d.type) for d in result.documents],
        summaries=result.summaries,
        concepts=result.concepts,
        entities=result.entities,
        reports=result.reports,
    )


@kb_router.get("/status", response_model=KBStatusResponse)
async def status_kb(
    kb_name: str = Query(..., pattern=_KB_NAME_PATTERN),
    settings: Settings = Depends(get_settings),
) -> KBStatusResponse:
    """Return health metrics for an existing knowledge base."""
    backend: StorageBackend = await get_kb_backend(kb_name, settings)
    result = await service_status_kb(backend, kb_name)
    return KBStatusResponse(
        kb_name=result.kb_name,
        total_indexed=result.total_indexed,
        last_compile=result.last_compile,
        last_lint=result.last_lint,
        directory_counts=result.directory_counts,
    )

