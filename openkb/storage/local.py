from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import portalocker.exceptions

from openkb.locks import atomic_write_bytes, kb_ingest_lock
from openkb.services import LockTimeoutError
from openkb.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class LocalStorageBackend(StorageBackend):
    """StorageBackend backed by the local filesystem.

    All blocking I/O runs in a thread via :func:`asyncio.to_thread` so the
    event loop is never stalled. Locking delegates to the existing
    :func:`~openkb.locks.kb_ingest_lock` (portalocker-based).

    Used by the CLI and by the local-dev API server.
    """

    def __init__(self, kb_dir: Path) -> None:
        self._kb_dir = kb_dir

    @property
    def kb_dir(self) -> Path:
        """Root directory of the KB instance (bridge to compiler layer)."""
        return self._kb_dir

    def _abs(self, path: str) -> Path:
        return self._kb_dir / path

    # --- Read ---

    async def read_bytes(self, path: str) -> bytes:
        abs_path = self._abs(path)
        return await asyncio.to_thread(abs_path.read_bytes)

    # --- Write ---

    async def write_bytes(self, path: str, content: bytes) -> None:
        abs_path = self._abs(path)
        await asyncio.to_thread(atomic_write_bytes, abs_path, content)

    # --- Metadata ---

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._abs(path).exists)

    async def get_mtime(self, path: str) -> float | None:
        def _mtime() -> float | None:
            try:
                return self._abs(path).stat().st_mtime
            except FileNotFoundError:
                return None
        return await asyncio.to_thread(_mtime)

    # --- Listing ---

    async def list_prefix(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            base = self._abs(prefix)
            if not base.exists():
                return []
            return [
                str(p.relative_to(self._kb_dir))
                for p in sorted(base.iterdir())
                if p.is_file()
            ]
        return await asyncio.to_thread(_list)

    # --- Delete ---

    async def delete(self, path: str) -> None:
        def _delete() -> None:
            self._abs(path).unlink(missing_ok=True)
        await asyncio.to_thread(_delete)

    # --- Locking ---

    @asynccontextmanager
    async def lock(
        self,
        resource: str = "ingest",
        *,
        timeout: float = 30.0,
    ) -> AsyncIterator[None]:
        """Acquire ``kb_ingest_lock`` in a background thread.

        Two :class:`threading.Event` objects coordinate the handshake:
        - ``_ready``: set by the background thread once the lock is held
          (or after a :exc:`portalocker.exceptions.LockException`).
        - ``_release``: set by the async side to tell the thread to drop the lock.
        """
        openkb_dir = self._kb_dir / ".openkb"
        _ready: threading.Event = threading.Event()
        _release: threading.Event = threading.Event()
        _error: list[Exception] = []

        def _hold_lock() -> None:
            try:
                with kb_ingest_lock(openkb_dir):
                    _ready.set()
                    _release.wait()
            except portalocker.exceptions.LockException:
                _error.append(LockTimeoutError(resource))
                _ready.set()

        thread = threading.Thread(target=_hold_lock, daemon=True)
        thread.start()

        # Wait (non-blocking for the event loop) until lock acquired or failed
        await asyncio.to_thread(_ready.wait)

        if _error:
            thread.join()
            raise _error[0]

        try:
            yield
        finally:
            _release.set()
            await asyncio.to_thread(thread.join)
