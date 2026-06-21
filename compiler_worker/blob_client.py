from __future__ import annotations

import logging
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


class BlobStorageClient:
    """Thin wrapper around Azure Blob Storage SDK.

    Blob paths follow the convention ``{container}/{blob_name}`` where
    ``container`` is the first path component (e.g. ``kb-<uuid>``) and
    ``blob_name`` is everything after the first ``/``.
    """

    def __init__(self, connection_string: str) -> None:
        self._service = BlobServiceClient.from_connection_string(connection_string)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split(blob_path: str) -> tuple[str, str]:
        """Split ``{container}/{blob_name}`` into ``(container, blob_name)``."""
        container, _, blob_name = blob_path.partition("/")
        return container, blob_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download_to_file(self, blob_path: str, dest: Path) -> None:
        """Download *blob_path* to *dest* on the local filesystem.

        Raises ``azure.core.exceptions.ResourceNotFoundError`` if the blob
        does not exist (propagated transparently to callers).
        """
        container, blob_name = self._split(blob_path)
        blob_client = self._service.get_blob_client(container=container, blob=blob_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            stream = blob_client.download_blob()
            stream.readinto(fh)
        logger.debug("Downloaded blob %s → %s", blob_path, dest)

    def upload_from_file(self, blob_path: str, src: Path) -> None:
        """Upload *src* to *blob_path* in Blob Storage (overwrites if present)."""
        container, blob_name = self._split(blob_path)
        blob_client = self._service.get_blob_client(container=container, blob=blob_name)
        with src.open("rb") as fh:
            blob_client.upload_blob(fh, overwrite=True)
        logger.debug("Uploaded %s → blob %s", src, blob_path)

    def ensure_container(self, container: str) -> None:
        """Create *container* if it does not already exist."""
        container_client = self._service.get_container_client(container)
        try:
            container_client.create_container()
            logger.debug("Created blob container: %s", container)
        except Exception as exc:
            # ResourceExistsError is expected on subsequent calls; swallow it.
            if "ContainerAlreadyExists" in type(exc).__name__ or "already exists" in str(exc).lower():
                logger.debug("Blob container already exists: %s", container)
            else:
                raise
