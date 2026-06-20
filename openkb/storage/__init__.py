from __future__ import annotations

from openkb.storage.azure_blob import AzureBlobStorageBackend
from openkb.storage.base import StorageBackend
from openkb.storage.local import LocalStorageBackend

__all__ = [
    "StorageBackend",
    "LocalStorageBackend",
    "AzureBlobStorageBackend",
    "get_backend",
]


def get_backend(kb_name: str, settings: object) -> StorageBackend:
    """Resolve a :class:`StorageBackend` from *settings* and *kb_name*.

    Args:
        kb_name: The KB slug (used as a path component or blob prefix).
        settings: A :class:`~openkb.api.deps.Settings` instance supplying
            ``storage_backend``, ``openkb_base_dir``,
            ``azure_storage_connection_string``, and ``azure_kb_container``.

    Returns:
        A :class:`LocalStorageBackend` when ``settings.storage_backend == "local"``,
        otherwise an :class:`AzureBlobStorageBackend`.
    """
    if getattr(settings, "storage_backend", "local") == "azure":
        return AzureBlobStorageBackend(
            connection_string=settings.azure_storage_connection_string,
            container_name=settings.azure_kb_container,
            kb_name=kb_name,
        )
    from pathlib import Path
    base_dir: Path = getattr(settings, "openkb_base_dir", Path("/data/kbs"))
    return LocalStorageBackend(kb_dir=base_dir / kb_name)
