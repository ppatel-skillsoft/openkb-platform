from __future__ import annotations

import json
import logging
from pathlib import Path

from openkb.services import DocumentEntry, KBListResult, KBNotFoundError
from openkb.storage.base import StorageBackend

logger = logging.getLogger(__name__)


async def service_list_kb(backend: StorageBackend, kb_name: str) -> KBListResult:
    """Return a structured listing of all documents and wiki pages in a KB.

    Raises:
        KBNotFoundError: KB does not exist.
    """
    if not await backend.exists(".openkb/config.yaml"):
        raise KBNotFoundError(kb_name)

    # Load documents from hashes.json
    documents: list[DocumentEntry] = []
    try:
        hashes_bytes = await backend.read_bytes(".openkb/hashes.json")
        registry: dict = json.loads(hashes_bytes)
        for meta in registry.values():
            raw_type = meta.get("type", "unknown")
            documents.append(DocumentEntry(
                name=meta.get("name", "unknown"),
                doc_name=meta.get("doc_name", Path(meta.get("name", "unknown")).stem),
                type=raw_type,
            ))
    except Exception:
        registry = {}

    # List wiki pages from each subdirectory
    async def _list_stems(prefix: str) -> list[str]:
        try:
            paths = await backend.list_prefix(prefix)
            return sorted(
                Path(p).stem
                for p in paths
                if Path(p).suffix == ".md" and Path(p).name != ".gitkeep"
            )
        except Exception:
            return []

    summaries = await _list_stems("wiki/summaries")
    concepts = await _list_stems("wiki/concepts")
    entities = await _list_stems("wiki/entities")

    # Reports: use full filename (name not stem) to mirror print_list
    try:
        report_paths = await backend.list_prefix("wiki/reports")
        reports = sorted(
            Path(p).name
            for p in report_paths
            if Path(p).suffix == ".md" and Path(p).name != ".gitkeep"
        )
    except Exception:
        reports = []

    return KBListResult(
        documents=documents,
        summaries=summaries,
        concepts=concepts,
        entities=entities,
        reports=reports,
    )
