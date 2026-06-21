from __future__ import annotations


class SidecarStartError(Exception):
    """Raised when the sidecar process fails to become healthy in time."""


class SidecarCompileError(Exception):
    """Raised when the sidecar reports ``status == 'failed'``."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class SidecarTimeoutError(Exception):
    """Raised when the compilation polling loop exceeds the deadline."""

    def __init__(self, timeout_s: int) -> None:
        self.timeout_s = timeout_s
        super().__init__(f"Compilation did not complete within {timeout_s}s")


class KBNotFoundError(Exception):
    """Raised when the ``knowledge_bases`` row for the job's ``kb_id`` is absent."""


class BlobNotFoundError(Exception):
    """Raised when the source blob cannot be found in Blob Storage."""
