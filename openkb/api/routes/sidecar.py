from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from openkb.schema import PAGE_CONTENT_DIRS
from openkb.services import (
    KBAlreadyExistsError,
    KBNotFoundError,
    LLMError,
    UnsupportedDocumentError,
)
from openkb.services.add_document import service_add_document
from openkb.services.init_kb import service_init_kb
from openkb.storage.local import LocalStorageBackend

logger = logging.getLogger(__name__)

sidecar_router = APIRouter()

# Fixed KB name — each sidecar process owns an isolated scratch directory
_KB_NAME = "kb"

# In-process compilation state; reset on each job
_state: dict = {
    "status": "idle",
    "pages": [],
    "token_cost": None,
    "pageindex_used": None,
    "error": None,
}
_compile_task: asyncio.Task | None = None

_DIR_TO_PAGE_TYPE: dict[str, str] = {
    "summaries": "summary",
    "concepts": "concept",
    "entities": "entity",
}


def _backend() -> LocalStorageBackend:
    return LocalStorageBackend(Path.cwd())


def _scan_wiki_pages() -> list[dict]:
    """Walk wiki/ in CWD and return page descriptors matching the contract."""
    wiki_dir = Path.cwd() / "wiki"
    pages: list[dict] = []
    if not wiki_dir.exists():
        return pages
    for md_file in sorted(wiki_dir.rglob("*.md")):
        if md_file.name.startswith("."):
            continue
        rel = md_file.relative_to(wiki_dir)
        parts = rel.parts
        if parts[0] in _DIR_TO_PAGE_TYPE:
            page_type = _DIR_TO_PAGE_TYPE[parts[0]]
            slug = str(rel.with_suffix(""))
        else:
            page_type = "index"
            slug = str(rel.with_suffix(""))
        pages.append({
            "slug": slug,
            "page_type": page_type,
            "entity_type": None,
            "file_path": str(md_file.relative_to(Path.cwd())),
        })
    return pages


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SidecarInitRequest(BaseModel):
    model: str | None = None
    language: str | None = None


class SidecarAddRequest(BaseModel):
    filename: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@sidecar_router.post("/init")
async def sidecar_init(body: SidecarInitRequest) -> dict:
    """Initialise KB in the sidecar's CWD (≡ `openkb init`)."""
    try:
        await service_init_kb(_backend(), _KB_NAME, body.model, body.language)
    except KBAlreadyExistsError:
        pass  # idempotent — treat as success
    return {"status": "ok"}


@sidecar_router.post("/add")
async def sidecar_add(body: SidecarAddRequest) -> dict:
    """Submit a document for async compilation (≡ `openkb add`)."""
    global _state, _compile_task

    _state = {
        "status": "compiling",
        "pages": [],
        "token_cost": None,
        "pageindex_used": None,
        "error": None,
    }

    async def _run() -> None:
        global _state
        try:
            source = str(Path.cwd() / "raw" / body.filename)
            result = await service_add_document(_backend(), _KB_NAME, source)
            if result.status == "failed":
                _state = {**_state, "status": "failed", "error": result.message}
                return
            pages = _scan_wiki_pages()
            _state = {
                "status": "complete",
                "pages": pages,
                "token_cost": None,
                "pageindex_used": False,
                "error": None,
            }
        except (KBNotFoundError, LLMError, UnsupportedDocumentError) as exc:
            _state = {**_state, "status": "failed", "error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error during sidecar compilation")
            _state = {**_state, "status": "failed", "error": str(exc)}

    _compile_task = asyncio.create_task(_run())
    return {"job_id": "sidecar-job"}


@sidecar_router.get("/status")
async def sidecar_status() -> dict:
    """Return current compilation state."""
    return _state
