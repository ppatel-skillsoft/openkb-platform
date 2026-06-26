"""Persistent KB sidecar pool — manages one long-lived openkb serve process per KB."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import shutil
import time

from generator_api.blob import rebuild_index_md, sync_wiki_tree
from generator_api.config import Settings
from generator_api.exceptions import SidecarCrashedError
from generator_api.sidecar import SidecarProcess

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _SidecarEntry:
    process: SidecarProcess
    lock: asyncio.Lock
    stale: bool = False
    last_used_at: float = dataclasses.field(default_factory=time.monotonic)


class SidecarPool:
    """Manages a pool of persistent openkb serve sidecar processes, one per KB.

    Concurrency contract (two-lock ordering — NEVER hold both simultaneously):
    1. Acquire ``_registry_lock`` (briefly) to get-or-create an entry.
    2. Release ``_registry_lock`` before acquiring ``entry.lock``.
    3. All sidecar I/O (start, init, teardown) happens while holding ``entry.lock`` only.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._registry: dict[str, _SidecarEntry] = {}
        self._registry_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_start(
        self,
        kb_id: str,
        kb_slug: str,
        container: str,
    ) -> SidecarProcess:
        """Return a healthy sidecar for *kb_id*, starting one if needed.

        Concurrent calls for the same *kb_id* are serialised through the
        per-entry lock — only one sidecar is ever started per KB.
        """
        # Phase 1: get-or-create entry under registry lock (held briefly)
        async with self._registry_lock:
            entry = self._registry.get(kb_id)
            if entry is None:
                # Insert placeholder so concurrent callers see an entry
                entry = _SidecarEntry(
                    process=SidecarProcess(),
                    lock=asyncio.Lock(),
                )
                self._registry[kb_id] = entry

        # Phase 2: serialise per-KB startup through the entry lock
        async with entry.lock:
            # Crash detection: if the process exited between queries, treat as stale
            if entry.process._process is not None and not entry.process.is_healthy():
                logger.warning(
                    "Sidecar for kb_id=%s crashed — restarting: %s",
                    kb_id,
                    SidecarCrashedError(kb_id),
                )
                entry.stale = True

            needs_start = not entry.process.is_healthy() or entry.stale

            if needs_start:
                # Tear down any existing process first
                if entry.process._process is not None:
                    await self._stop_entry(kb_id, entry, reason="restart")
                    entry.process = SidecarProcess()
                    entry.stale = False

                await self._start_sidecar(kb_id, kb_slug, container, entry)

            entry.last_used_at = time.monotonic()

        return entry.process

    def update_last_used(self, kb_id: str) -> None:
        """Touch last_used_at for *kb_id* under the registry lock."""
        entry = self._registry.get(kb_id)
        if entry is not None:
            entry.last_used_at = time.monotonic()

    def invalidate(self, kb_id: str) -> None:
        """Mark the sidecar for *kb_id* as stale; it will restart on next query."""
        entry = self._registry.get(kb_id)
        if entry is not None:
            entry.stale = True
            logger.info("KB %s marked stale — will restart on next query", kb_id)
        else:
            logger.debug(
                "invalidate called for KB %s with no active sidecar — no-op", kb_id
            )

    async def stop_kb(self, kb_id: str) -> None:
        """Stop and remove the sidecar for *kb_id*. No-op if not running."""
        async with self._registry_lock:
            entry = self._registry.pop(kb_id, None)
        if entry is None:
            return
        async with entry.lock:
            await self._stop_entry(kb_id, entry, reason="stop_kb")

    async def shutdown(self) -> None:
        """Stop all running sidecars. Called on FastAPI lifespan exit."""
        async with self._registry_lock:
            entries = list(self._registry.items())
            self._registry.clear()

        for kb_id, entry in entries:
            try:
                await self._stop_entry(kb_id, entry, reason="shutdown")
            except Exception:
                logger.exception(
                    "Error stopping sidecar for kb_id=%s during shutdown", kb_id
                )

        logger.info("SidecarPool shut down (%d sidecars stopped)", len(entries))

    async def _evict_idle(self) -> None:
        """Stop sidecars idle longer than ``sidecar_idle_ttl_seconds``."""
        ttl = self._settings.sidecar_idle_ttl_seconds
        now = time.monotonic()

        async with self._registry_lock:
            idle = [
                (kb_id, entry)
                for kb_id, entry in self._registry.items()
                if (now - entry.last_used_at) > ttl or entry.stale
            ]

        for kb_id, entry in idle:
            elapsed = now - entry.last_used_at
            logger.info(
                "Evicting idle sidecar kb_id=%s (idle=%.0fs > ttl=%ds)",
                kb_id,
                elapsed,
                ttl,
            )
            async with entry.lock:
                await self._stop_entry(kb_id, entry, reason="idle_eviction")
            async with self._registry_lock:
                self._registry.pop(kb_id, None)

    async def evict_idle_loop(self) -> None:
        """Background task: run ``_evict_idle`` every 60 seconds until cancelled."""
        while True:
            try:
                await asyncio.sleep(60)
                await self._evict_idle()
            except asyncio.CancelledError:
                logger.info("evict_idle_loop cancelled — exiting")
                break

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _start_sidecar(
        self,
        kb_id: str,
        kb_slug: str,
        container: str,
        entry: _SidecarEntry,
    ) -> None:
        """Sync wiki blobs, rebuild index, start and init the sidecar subprocess."""
        scratch_dir = self._settings.scratch_dir_root / kb_id
        scratch_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Starting sidecar for kb_id=%s (kb_slug=%s, container=%s)",
            kb_id,
            kb_slug,
            container,
        )

        # Sync all wiki blobs from blob storage into the persistent scratch dir
        await asyncio.wait_for(
            sync_wiki_tree(
                connection_string=self._settings.azure_storage_connection_string,
                container=container,
                kb_blob_prefix="wiki/",
                scratch_dir=scratch_dir / kb_slug,
            ),
            timeout=self._settings.sidecar_startup_timeout,
        )

        # Rebuild the aggregate index.md — each compiler job writes a per-job
        # index that only reflects its own session; this rebuilds from all pages.
        wiki_dir = scratch_dir / kb_slug / "wiki"
        if wiki_dir.is_dir():
            rebuild_index_md(wiki_dir)

        # Start sidecar subprocess and send /kb/init
        await asyncio.to_thread(
            entry.process.start,
            scratch_dir,
            kb_slug,
            self._settings.llm_api_key,
            self._settings.sidecar_startup_timeout,
        )
        await asyncio.to_thread(entry.process.init, kb_slug)

        logger.info("Sidecar ready for kb_id=%s on port %s", kb_id, entry.process._port)

    async def _stop_entry(
        self,
        kb_id: str,
        entry: _SidecarEntry,
        reason: str,
    ) -> None:
        """Teardown sidecar subprocess and remove its scratch directory."""
        await asyncio.to_thread(entry.process.teardown)
        scratch_dir = self._settings.scratch_dir_root / kb_id
        shutil.rmtree(scratch_dir, ignore_errors=True)
        logger.info("Sidecar for kb_id=%s stopped (reason: %s)", kb_id, reason)
