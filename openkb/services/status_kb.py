from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from openkb.services import KBNotFoundError, KBStatusResult
from openkb.storage.base import StorageBackend

logger = logging.getLogger(__name__)

_PAGE_CONTENT_DIRS = ("summaries", "concepts", "entities")


async def service_status_kb(backend: StorageBackend, kb_name: str) -> KBStatusResult:
    """Return a health/metrics snapshot of an existing KB.

    Raises:
        KBNotFoundError: KB does not exist.
    """
    if not await backend.exists(".openkb/config.yaml"):
        raise KBNotFoundError(kb_name)

    # Total indexed documents
    total_indexed = 0
    try:
        hashes_bytes = await backend.read_bytes(".openkb/hashes.json")
        registry: dict = json.loads(hashes_bytes)
        total_indexed = len(registry)
    except Exception:
        pass

    # last_compile: max mtime across summaries, concepts, entities
    last_compile: str | None = None
    for subdir in _PAGE_CONTENT_DIRS:
        try:
            paths = await backend.list_prefix(f"wiki/{subdir}")
            for p in paths:
                if p.endswith(".gitkeep"):
                    continue
                mtime = await backend.get_mtime(p)
                if mtime is not None:
                    ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                    if last_compile is None or ts > last_compile:
                        last_compile = ts
        except Exception:
            continue

    # last_lint: max mtime across reports/
    last_lint: str | None = None
    try:
        report_paths = await backend.list_prefix("wiki/reports")
        for p in report_paths:
            if p.endswith(".gitkeep"):
                continue
            mtime = await backend.get_mtime(p)
            if mtime is not None:
                ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                if last_lint is None or ts > last_lint:
                    last_lint = ts
    except Exception:
        pass

    # Directory counts
    async def _count(prefix: str) -> int:
        try:
            paths = await backend.list_prefix(prefix)
            return sum(1 for p in paths if not p.endswith(".gitkeep"))
        except Exception:
            return 0

    directory_counts = {
        "sources": await _count("wiki/sources"),
        "summaries": await _count("wiki/summaries"),
        "concepts": await _count("wiki/concepts"),
        "entities": await _count("wiki/entities"),
        "reports": await _count("wiki/reports"),
        "raw": await _count("raw"),
    }

    return KBStatusResult(
        kb_name=kb_name,
        total_indexed=total_indexed,
        last_compile=last_compile,
        last_lint=last_lint,
        directory_counts=directory_counts,
    )
