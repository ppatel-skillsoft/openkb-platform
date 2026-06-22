"""Azure Blob Storage helpers for seeding and cleaning KB fixtures.

Uses the azure-storage-blob async SDK against the Azurite emulator.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from azure.storage.blob.aio import BlobServiceClient

logger = logging.getLogger(__name__)


async def get_blob_service_client(connection_string: str) -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(connection_string)


async def seed_blobs(
    connection_string: str,
    container: str,
    blobs: dict[str, str],
) -> None:
    """Upload *blobs* mapping {blob_path: content} to *container*.

    Creates the container if it does not exist. Each blob is uploaded
    unconditionally (overwrite=True) so the seeding is idempotent.
    """
    async with BlobServiceClient.from_connection_string(connection_string) as svc:
        container_client = svc.get_container_client(container)
        try:
            await container_client.create_container()
        except Exception:
            pass  # already exists — fine

        for path, content in blobs.items():
            blob_client = container_client.get_blob_client(path)
            await blob_client.upload_blob(
                content.encode() if isinstance(content, str) else content,
                overwrite=True,
            )
            logger.debug("Seeded blob %s/%s", container, path)


async def list_kb_blobs(
    connection_string: str,
    container: str,
    prefix: str,
) -> list[str]:
    """Return all blob names under *prefix* in *container*."""
    result: list[str] = []
    async with BlobServiceClient.from_connection_string(connection_string) as svc:
        container_client = svc.get_container_client(container)
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            result.append(blob.name)
    return result


async def delete_kb_blobs(
    connection_string: str,
    container: str,
    prefix: str,
) -> None:
    """Delete all blobs with names starting with *prefix* from *container*.

    Idempotent — silently skips blobs that no longer exist.
    """
    async with BlobServiceClient.from_connection_string(connection_string) as svc:
        container_client = svc.get_container_client(container)
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            try:
                await container_client.delete_blob(blob.name)
                logger.debug("Deleted blob %s/%s", container, blob.name)
            except Exception as exc:
                logger.warning("Could not delete blob %s: %s", blob.name, exc)
