from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from compiler_worker.blob_client import BlobStorageClient


def _make_client() -> tuple[BlobStorageClient, MagicMock]:
    mock_service = MagicMock()
    with patch("azure.storage.blob.BlobServiceClient.from_connection_string", return_value=mock_service):
        client = BlobStorageClient("fake-conn-string")
    client._service = mock_service
    return client, mock_service


class TestDownloadToFile:
    def test_splits_container_and_blob_name(self, tmp_path):
        client, mock_service = _make_client()

        mock_blob_client = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob_client
        mock_stream = MagicMock()
        mock_blob_client.download_blob.return_value = mock_stream

        dest = tmp_path / "raw" / "file.md"
        client.download_to_file("kb-abc/raw/file.md", dest)

        mock_service.get_blob_client.assert_called_once_with(
            container="kb-abc", blob="raw/file.md"
        )

    def test_creates_parent_directories(self, tmp_path):
        client, mock_service = _make_client()
        mock_blob_client = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob_client
        mock_stream = MagicMock()
        mock_blob_client.download_blob.return_value = mock_stream

        dest = tmp_path / "a" / "b" / "c" / "file.md"
        client.download_to_file("container/raw/file.md", dest)

        assert dest.parent.exists()


class TestUploadFromFile:
    def test_constructs_correct_container_and_blob_name(self, tmp_path):
        client, mock_service = _make_client()
        mock_blob_client = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob_client

        src = tmp_path / "wiki" / "summaries" / "report.md"
        src.parent.mkdir(parents=True)
        src.write_text("content")

        client.upload_from_file("kb-abc/wiki/summaries/report.md", src)

        mock_service.get_blob_client.assert_called_once_with(
            container="kb-abc", blob="wiki/summaries/report.md"
        )
        mock_blob_client.upload_blob.assert_called_once()


class TestEnsureContainer:
    def test_calls_create_container_when_absent(self):
        client, mock_service = _make_client()
        mock_container_client = MagicMock()
        mock_service.get_container_client.return_value = mock_container_client

        client.ensure_container("kb-abc")

        mock_container_client.create_container.assert_called_once()

    def test_swallows_already_exists_error(self):
        client, mock_service = _make_client()
        mock_container_client = MagicMock()
        mock_service.get_container_client.return_value = mock_container_client

        class FakeAlreadyExists(Exception):
            pass

        FakeAlreadyExists.__name__ = "ContainerAlreadyExistsError"
        mock_container_client.create_container.side_effect = FakeAlreadyExists("ContainerAlreadyExists")

        # Should not raise
        client.ensure_container("kb-abc")
