from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Service result types
# ---------------------------------------------------------------------------

@dataclass
class KBInitResult:
    status: Literal["created", "exists"]
    kb_name: str
    message: str


@dataclass
class KBAddResult:
    status: Literal["added", "skipped", "failed"]
    doc_name: str | None
    message: str


@dataclass
class KBQueryResult:
    answer: str
    saved_to: str | None  # blob path or local path when save=True, else None


@dataclass
class DocumentEntry:
    name: str      # original filename
    doc_name: str  # collision-resistant slug
    type: str      # "short" | "pageindex" | raw extension


@dataclass
class KBListResult:
    documents: list[DocumentEntry]
    summaries: list[str]   # sorted page stems
    concepts: list[str]
    entities: list[str]
    reports: list[str]


@dataclass
class KBStatusResult:
    kb_name: str
    total_indexed: int
    last_compile: str | None   # ISO-8601 UTC or None
    last_lint: str | None      # ISO-8601 UTC or None
    directory_counts: dict[str, int]  # subdir name → file count


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class OpenKBError(Exception):
    """Base class for all OpenKB service exceptions."""


class KBNotFoundError(OpenKBError):
    def __init__(self, kb_name: str) -> None:
        self.kb_name = kb_name
        super().__init__(
            f"KB '{kb_name}' not found. Call POST /kb/init (or openkb init) to create it."
        )


class KBAlreadyExistsError(OpenKBError):
    def __init__(self, kb_name: str) -> None:
        self.kb_name = kb_name
        super().__init__(f"KB '{kb_name}' already exists.")


class UnsupportedDocumentError(OpenKBError):
    def __init__(self, ext: str, supported: set[str]) -> None:
        self.ext = ext
        self.supported = supported
        super().__init__(
            f"Unsupported file extension '{ext}'. "
            f"Supported extensions: {sorted(supported)}"
        )


class URLFetchError(OpenKBError):
    def __init__(self, url: str, detail: str) -> None:
        self.url = url
        self.detail = detail
        super().__init__(f"Failed to fetch URL '{url}': {detail}")


class LLMError(OpenKBError):
    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"LLM error: {detail}")


class LockTimeoutError(OpenKBError):
    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(
            f"KB is busy (could not acquire lock on '{resource}'). "
            "Retry after a moment."
        )

from openkb.services.query_kb import service_query_kb
from openkb.services.init_kb import service_init_kb
from openkb.services.add_document import service_add_document
from openkb.services.list_kb import service_list_kb
from openkb.services.status_kb import service_status_kb
__all__ = [
    "KBInitResult", "KBAddResult", "KBQueryResult", "KBListResult", "KBStatusResult",
    "DocumentEntry",
    "OpenKBError", "KBNotFoundError", "KBAlreadyExistsError",
    "UnsupportedDocumentError", "URLFetchError", "LLMError", "LockTimeoutError",
    "service_query_kb",
    "service_init_kb",
    "service_add_document",
    "service_list_kb",
    "service_status_kb",
]
