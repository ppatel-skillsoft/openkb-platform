from __future__ import annotations

import logging
from pathlib import Path

from azure.core.exceptions import AzureError
from azure.storage.blob.aio import BlobServiceClient

from generator_api.exceptions import BlobSyncError

logger = logging.getLogger(__name__)


async def check_azurite(connection_string: str) -> str:
    """Probe Azurite by listing containers. Returns 'ok' or 'error: {msg}'."""
    try:
        async with BlobServiceClient.from_connection_string(connection_string) as svc:
            async for _ in svc.list_containers():
                break  # Just need to confirm connectivity
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Azurite health check failed: %s", exc)
        return f"error: {exc}"


async def sync_wiki_tree(
    connection_string: str,
    container: str,
    kb_blob_prefix: str,
    scratch_dir: Path,
) -> None:
    """Download all wiki blobs for a KB to *scratch_dir*/wiki/.

    Args:
        connection_string: Azure Blob Storage connection string.
        container: Container name (e.g. ``kb-<uuid>``).
        kb_blob_prefix: Blob name prefix pointing to the wiki tree
            (e.g. ``wiki/``). All blobs under this prefix are downloaded.
        scratch_dir: Per-request scratch directory; wiki files land in
            ``scratch_dir/wiki/``.

    Raises:
        BlobSyncError: If zero blobs are found or any download fails.
    """
    prefix = "wiki/"
    downloaded = 0

    try:
        async with BlobServiceClient.from_connection_string(connection_string) as svc:
            container_client = svc.get_container_client(container)

            async for blob in container_client.list_blobs(name_starts_with=prefix):
                blob_name: str = blob.name  # e.g. wiki/summaries/hello.md
                # Relative path under scratch_dir: keep the full blob_name so
                # the sidecar sees wiki/... at its root.
                dest = scratch_dir / blob_name
                dest.parent.mkdir(parents=True, exist_ok=True)

                blob_client = container_client.get_blob_client(blob_name)
                try:
                    stream = await blob_client.download_blob()
                    content = await stream.readall()
                    dest.write_bytes(content)
                    logger.debug("Synced blob %s → %s", blob_name, dest)
                    downloaded += 1
                except AzureError as exc:
                    raise BlobSyncError(
                        f"Failed to download blob {blob_name}: {exc}"
                    ) from exc

    except BlobSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BlobSyncError(f"Blob storage unavailable: {exc}") from exc

    if downloaded == 0:
        raise BlobSyncError(
            f"Wiki is empty for KB — no blobs found under {container}/{prefix}"
        )

    logger.info("Synced %d wiki blobs from %s/%s → %s", downloaded, container, prefix, scratch_dir)
