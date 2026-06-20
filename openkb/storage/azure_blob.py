from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator

from openkb.services import LockTimeoutError
from openkb.storage.base import StorageBackend

if TYPE_CHECKING:
    from azure.storage.blob.aio import BlobServiceClient

logger = logging.getLogger(__name__)

_LOCK_BLOB_SUFFIX = ".openkb/ingest.lock"
_LEASE_DURATION = 60   # seconds; auto-expires so a crashed process doesn't deadlock
_POLL_INTERVAL = 1.0   # seconds between lease-acquire retries


class AzureBlobStorageBackend(StorageBackend):
    """StorageBackend backed by Azure Blob Storage (or Azurite for local dev).

    Blob names are scoped as ``<kb_name>/<relative_path>`` within a single
    container. Switching between Azurite and real Azure requires only changing
    ``AZURE_STORAGE_CONNECTION_STRING`` — no code changes.

    Locking uses Azure Blob Lease on a dedicated ``ingest.lock`` blob.
    """

    def __init__(
        self,
        connection_string: str,
        container_name: str,
        kb_name: str,
    ) -> None:
        self._connection_string = connection_string
        self._container_name = container_name
        self._kb_name = kb_name
        self._client: BlobServiceClient | None = None

    def _get_client(self) -> BlobServiceClient:
        if self._client is None:
            from azure.storage.blob.aio import BlobServiceClient
            self._client = BlobServiceClient.from_connection_string(self._connection_string)
        return self._client

    def _blob_name(self, path: str) -> str:
        return f"{self._kb_name}/{path}"

    def _container_client(self):
        return self._get_client().get_container_client(self._container_name)

    def _blob_client(self, path: str):
        return self._get_client().get_blob_client(
            container=self._container_name,
            blob=self._blob_name(path),
        )

    # --- Read ---

    async def read_bytes(self, path: str) -> bytes:
        client = self._blob_client(path)
        try:
            stream = await client.download_blob()
            return await stream.readall()
        except Exception as exc:
            from azure.core.exceptions import ResourceNotFoundError
            if isinstance(exc, ResourceNotFoundError):
                raise FileNotFoundError(f"Blob not found: {self._blob_name(path)}") from exc
            raise

    # --- Write ---

    async def write_bytes(self, path: str, content: bytes) -> None:
        client = self._blob_client(path)
        await client.upload_blob(content, overwrite=True)

    # --- Metadata ---

    async def exists(self, path: str) -> bool:
        client = self._blob_client(path)
        try:
            await client.get_blob_properties()
            return True
        except Exception:
            return False

    async def get_mtime(self, path: str) -> float | None:
        client = self._blob_client(path)
        try:
            props = await client.get_blob_properties()
            last_modified = props.get("last_modified")
            if last_modified is None:
                return None
            return last_modified.timestamp()
        except Exception:
            return None

    # --- Listing ---

    async def list_prefix(self, prefix: str) -> list[str]:
        full_prefix = f"{self._kb_name}/{prefix}"
        container = self._container_client()
        results: list[str] = []
        async for blob in container.list_blobs(name_starts_with=full_prefix):
            name: str = blob.name
            # Strip the kb_name prefix to return KB-relative paths
            relative = name[len(self._kb_name) + 1:]
            results.append(relative)
        return sorted(results)

    # --- Delete ---

    async def delete(self, path: str) -> None:
        client = self._blob_client(path)
        try:
            await client.delete_blob()
        except Exception:
            pass  # no-op if already absent

    # --- Locking ---

    @asynccontextmanager
    async def lock(
        self,
        resource: str = "ingest",
        *,
        timeout: float = 30.0,
    ) -> AsyncIterator[None]:
        """Acquire a Blob Lease on ``<kb_name>/.openkb/ingest.lock``.

        Polls every :data:`_POLL_INTERVAL` seconds up to ``timeout``.
        The lease auto-expires after :data:`_LEASE_DURATION` seconds so a
        crashed process can never deadlock.
        """
        lock_path = _LOCK_BLOB_SUFFIX
        lock_client = self._blob_client(lock_path)

        # Ensure the lock blob exists (no-op if already present)
        try:
            await lock_client.get_blob_properties()
        except Exception:
            try:
                await lock_client.upload_blob(b"", overwrite=False)
            except Exception:
                pass  # another process may have created it concurrently

        from azure.storage.blob.aio import BlobLeaseClient
        from azure.core.exceptions import HttpResponseError

        elapsed = 0.0
        lease_client: BlobLeaseClient | None = None

        while elapsed < timeout:
            try:
                lease_client = await lock_client.acquire_lease(lease_duration=_LEASE_DURATION)
                break
            except HttpResponseError:
                await asyncio.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL

        if lease_client is None:
            raise LockTimeoutError(resource)

        try:
            yield
        finally:
            try:
                await lease_client.release()
            except Exception:
                logger.warning("Failed to release blob lease on %s", self._blob_name(lock_path))

    # --- Compiler bridge ---

    @asynccontextmanager
    async def local_working_dir(self) -> AsyncIterator[Path]:
        """Download all KB blobs to a temp dir, yield the path, then sync back.

        Service functions that call into the path-based compiler layer use this
        context manager to materialise a local filesystem view of the KB.
        """
        # Internal management blobs that must never be overwritten during sync-back.
        # ingest.lock may be actively leased — uploading over it would fail.
        _SKIP_BLOBS = {_LOCK_BLOB_SUFFIX}

        with tempfile.TemporaryDirectory(prefix="openkb-") as tmpdir:
            kb_dir = Path(tmpdir)
            # Download all blobs under <kb_name>/ (skip internal lock blob)
            prefix = f"{self._kb_name}/"
            container = self._container_client()
            async for blob in container.list_blobs(name_starts_with=prefix):
                relative = blob.name[len(prefix):]
                if relative in _SKIP_BLOBS:
                    continue
                local_path = kb_dir / relative
                local_path.parent.mkdir(parents=True, exist_ok=True)
                blob_client = self._get_client().get_blob_client(
                    container=self._container_name,
                    blob=blob.name,
                )
                stream = await blob_client.download_blob()
                local_path.write_bytes(await stream.readall())

            # Snapshot existing files so we know what changed on exit
            before = {
                str(p.relative_to(kb_dir))
                for p in kb_dir.rglob("*")
                if p.is_file()
            }

            yield kb_dir

            # Upload new and changed files back to blob storage (skip internal blobs)
            after = {
                str(p.relative_to(kb_dir))
                for p in kb_dir.rglob("*")
                if p.is_file()
            }
            for rel in after:
                if rel in _SKIP_BLOBS:
                    continue
                local_path = kb_dir / rel
                if rel not in before or local_path.stat().st_mtime > 0:
                    await self.write_bytes(rel, local_path.read_bytes())
