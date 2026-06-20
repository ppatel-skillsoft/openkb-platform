from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class StorageBackend(ABC):
    """Async I/O and locking interface for a single KB instance.

    All methods are async. Implementations must satisfy this contract
    without exception. Paths are always relative to the KB root.
    """

    # --- Read ---

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes:
        """Read file at ``path``. Raises :exc:`FileNotFoundError` if absent."""

    async def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read file at ``path`` as text (UTF-8 by default)."""
        return (await self.read_bytes(path)).decode(encoding)

    # --- Write ---

    @abstractmethod
    async def write_bytes(self, path: str, content: bytes) -> None:
        """Atomically write ``content`` to ``path``. Creates parent dirs."""

    async def write_text(self, path: str, content: str, encoding: str = "utf-8") -> None:
        """Write ``content`` as text to ``path``."""
        await self.write_bytes(path, content.encode(encoding))

    # --- Metadata ---

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Return ``True`` if ``path`` exists."""

    @abstractmethod
    async def get_mtime(self, path: str) -> float | None:
        """Return last-modified POSIX timestamp, or ``None`` if not found."""

    # --- Listing ---

    @abstractmethod
    async def list_prefix(self, prefix: str) -> list[str]:
        """Return relative paths of all files under ``prefix/`` (non-recursive)."""

    # --- Delete ---

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete file at ``path``. No-op if already absent."""

    # --- Locking ---

    @asynccontextmanager
    @abstractmethod
    async def lock(
        self,
        resource: str = "ingest",
        *,
        timeout: float = 30.0,
    ) -> AsyncIterator[None]:
        """Acquire exclusive write lock for ``resource``.

        Raises :exc:`~openkb.services.LockTimeoutError` if the lock cannot
        be acquired within ``timeout`` seconds.
        """
        ...  # pragma: no cover
        yield  # pragma: no cover
