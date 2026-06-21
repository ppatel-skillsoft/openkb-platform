from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompilationJob:
    """Deserialised from a Redis queue message."""

    job_id: str
    kb_id: str
    document_id: str
    blob_path: str
    filename: str
    enqueued_at: str


@dataclass
class SidecarPage:
    """One page entry from the sidecar ``GET /status`` response."""

    slug: str
    page_type: str
    entity_type: str | None
    file_path: str


@dataclass
class SidecarStatus:
    """Full response from sidecar ``GET /status``."""

    status: str
    pages: list[SidecarPage] = field(default_factory=list)
    token_cost: int | None = None
    pageindex_used: bool | None = None
    error: str | None = None
