from __future__ import annotations


class KBNotFoundError(Exception):
    def __init__(self, kb_id: str) -> None:
        super().__init__(f"Knowledge base {kb_id} not found")
        self.kb_id = kb_id


class KBNotReadyError(Exception):
    def __init__(self, kb_id: str) -> None:
        super().__init__(f"Knowledge base {kb_id} has no compiled documents")
        self.kb_id = kb_id


class DocumentNotFoundError(Exception):
    def __init__(self, doc_id: str, kb_id: str) -> None:
        super().__init__(f"Document {doc_id} not found in knowledge base {kb_id}")
        self.doc_id = doc_id
        self.kb_id = kb_id


class BlobSyncError(Exception):
    """Raised when the wiki tree cannot be synced from Blob Storage."""


class SidecarStartError(Exception):
    """Raised when the sidecar fails to become healthy within the timeout."""


class SidecarQueryError(Exception):
    """Raised when the sidecar returns a non-2xx response."""


class SidecarCrashedError(Exception):
    def __init__(self, kb_id: str) -> None:
        super().__init__(f"Sidecar for KB {kb_id} crashed unexpectedly")
        self.kb_id = kb_id
