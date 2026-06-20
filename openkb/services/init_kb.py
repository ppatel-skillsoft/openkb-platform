from __future__ import annotations

import json
import logging

import yaml

from openkb.config import DEFAULT_CONFIG
from openkb.schema import AGENTS_MD, INDEX_SEED
from openkb.services import KBAlreadyExistsError, KBInitResult
from openkb.storage.base import StorageBackend

logger = logging.getLogger(__name__)

# Subdirectories to scaffold as stub entries so blob storage "directories" exist
_WIKI_STUB_DIRS = (
    "wiki/summaries",
    "wiki/concepts",
    "wiki/entities",
    "wiki/reports",
    "wiki/explorations",
    "wiki/sources/images",
)


async def service_init_kb(
    backend: StorageBackend,
    kb_name: str,
    model: str | None,
    language: str | None,
) -> KBInitResult:
    """Initialise a new knowledge base.

    Creates the full directory structure (``.openkb/``, ``wiki/``, ``raw/``)
    via the storage backend. Works identically against the local filesystem
    and Azure Blob Storage / Azurite.

    Raises:
        KBAlreadyExistsError: if ``.openkb/config.yaml`` already exists.
    """
    if await backend.exists(".openkb/config.yaml"):
        raise KBAlreadyExistsError(kb_name)

    resolved_model = (model or "").strip() or DEFAULT_CONFIG["model"]
    resolved_language = (language or "").strip() or DEFAULT_CONFIG["language"]

    config = {
        "model": resolved_model,
        "language": resolved_language,
        "pageindex_threshold": DEFAULT_CONFIG["pageindex_threshold"],
    }

    # .openkb/ state files
    await backend.write_text(".openkb/config.yaml", yaml.safe_dump(config, allow_unicode=True))
    await backend.write_text(".openkb/hashes.json", json.dumps({}, indent=2) + "\n")
    # Dedicated lock blob used by AzureBlobStorageBackend.lock()
    await backend.write_bytes(".openkb/ingest.lock", b"")

    # wiki/ structure
    await backend.write_text("wiki/AGENTS.md", AGENTS_MD)
    await backend.write_text("wiki/index.md", INDEX_SEED)
    await backend.write_text("wiki/log.md", "# Operations Log\n\n")

    # Scaffold subdirectories with a .gitkeep so blob storage "directories" exist
    for subdir in _WIKI_STUB_DIRS:
        await backend.write_bytes(f"{subdir}/.gitkeep", b"")

    # raw/ input directory
    await backend.write_bytes("raw/.gitkeep", b"")

    return KBInitResult(
        status="created",
        kb_name=kb_name,
        message=f"Knowledge base '{kb_name}' initialised.",
    )
