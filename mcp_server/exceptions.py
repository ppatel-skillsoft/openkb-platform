from __future__ import annotations


class KBNotFoundError(Exception):
    """Raised when the requested knowledge base does not exist in the database."""

    def __init__(self, kb_id: str) -> None:
        super().__init__(f"Knowledge base {kb_id!r} not found")
        self.kb_id = kb_id


class KBNotReadyError(Exception):
    """Raised when a KB exists but has no compiled documents yet."""

    def __init__(self, kb_id: str) -> None:
        super().__init__(f"Knowledge base {kb_id!r} has no compiled documents")
        self.kb_id = kb_id


class GeneratorAPIError(Exception):
    """Raised when the generator-api returns an unexpected error or times out."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code
