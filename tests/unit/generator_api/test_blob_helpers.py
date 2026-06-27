from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import AzureError, ResourceNotFoundError

from generator_api.blob import delete_summary_blob, upload_index_to_blob
from generator_api.exceptions import BlobSyncError

_CONN = "fake-connection-string"
_CONTAINER = "kb-test"
_SLUG = "my-document"


def _patch_svc(mock_container_client: MagicMock):
    """Return a context-manager patch for BlobServiceClient that yields *mock_container_client*."""
    mock_svc = MagicMock()
    mock_svc.get_container_client.return_value = mock_container_client
    mock_svc_cm = MagicMock()
    mock_svc_cm.__aenter__ = AsyncMock(return_value=mock_svc)
    mock_svc_cm.__aexit__ = AsyncMock(return_value=False)
    return patch("generator_api.blob.BlobServiceClient.from_connection_string", return_value=mock_svc_cm)


@pytest.mark.asyncio
async def test_delete_summary_blob_success() -> None:
    """Blob exists and is deleted without error."""
    mock_blob_client = AsyncMock()
    mock_container = MagicMock()
    mock_container.get_blob_client.return_value = mock_blob_client

    with _patch_svc(mock_container):
        await delete_summary_blob(_CONN, _CONTAINER, _SLUG)

    mock_container.get_blob_client.assert_called_once_with(f"wiki/summaries/{_SLUG}.md")
    mock_blob_client.delete_blob.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_summary_blob_already_gone() -> None:
    """ResourceNotFoundError from delete_blob is swallowed silently."""
    mock_blob_client = AsyncMock()
    mock_blob_client.delete_blob.side_effect = ResourceNotFoundError()
    mock_container = MagicMock()
    mock_container.get_blob_client.return_value = mock_blob_client

    with _patch_svc(mock_container):
        # Must not raise
        await delete_summary_blob(_CONN, _CONTAINER, _SLUG)


@pytest.mark.asyncio
async def test_delete_summary_blob_azure_error() -> None:
    """Non-ResourceNotFoundError AzureError is re-raised as BlobSyncError."""
    mock_blob_client = AsyncMock()
    mock_blob_client.delete_blob.side_effect = AzureError("storage unavailable")
    mock_container = MagicMock()
    mock_container.get_blob_client.return_value = mock_blob_client

    with _patch_svc(mock_container):
        with pytest.raises(BlobSyncError, match="storage unavailable"):
            await delete_summary_blob(_CONN, _CONTAINER, _SLUG)


@pytest.mark.asyncio
async def test_upload_index_to_blob_success(tmp_path: Path) -> None:
    """index.md is read and uploaded to wiki/index.md with overwrite=True."""
    index_file = tmp_path / "index.md"
    index_file.write_text("# Knowledge Base Index\n", encoding="utf-8")

    mock_blob_client = AsyncMock()
    mock_container = MagicMock()
    mock_container.get_blob_client.return_value = mock_blob_client

    with _patch_svc(mock_container):
        await upload_index_to_blob(_CONN, _CONTAINER, index_file)

    mock_container.get_blob_client.assert_called_once_with("wiki/index.md")
    mock_blob_client.upload_blob.assert_awaited_once_with(
        "# Knowledge Base Index\n", overwrite=True
    )


@pytest.mark.asyncio
async def test_upload_index_to_blob_azure_error(tmp_path: Path) -> None:
    """AzureError during upload is wrapped in BlobSyncError."""
    index_file = tmp_path / "index.md"
    index_file.write_text("# Index", encoding="utf-8")

    mock_blob_client = AsyncMock()
    mock_blob_client.upload_blob.side_effect = AzureError("upload failed")
    mock_container = MagicMock()
    mock_container.get_blob_client.return_value = mock_blob_client

    with _patch_svc(mock_container):
        with pytest.raises(BlobSyncError, match="upload failed"):
            await upload_index_to_blob(_CONN, _CONTAINER, index_file)

