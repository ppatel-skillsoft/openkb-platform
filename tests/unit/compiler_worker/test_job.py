"""Unit tests for compiler_worker.blob_client.rebuild_and_upload_index — T030."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from compiler_worker.blob_client import BlobStorageClient
from compiler_worker.config import WorkerConfig


def _make_config(**overrides) -> WorkerConfig:
    base = dict(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        blob_connection_string="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;",
        sidecar_cmd="openkb",
        kb_id="6644cfee-e287-4e6d-a29b-f873e5eb64e8",
    )
    base.update(overrides)
    return WorkerConfig(**base)


def _make_blob_client(config: WorkerConfig) -> BlobStorageClient:
    with patch("compiler_worker.blob_client.BlobServiceClient"):
        return BlobStorageClient(config.blob_connection_string)


def _mock_blob_props(name: str) -> MagicMock:
    props = MagicMock()
    props.name = name
    return props


def test_rebuild_and_upload_index_generates_sections() -> None:
    """rebuild_and_upload_index groups blobs into Documents/Concepts/Entities (T030a)."""
    client = _make_blob_client(_make_config())

    summary_content = "---\ntitle: Marketing Overview\ndescription: High-level summary\n---\n# Content"
    concept_content = "---\ntitle: Brand Awareness\n---\n# Concept"
    entity_content = "---\ntitle: Skillsoft\ndescription: The company\n---\n# Entity"

    blobs = [
        _mock_blob_props("wiki/summaries/marketing-overview.md"),
        _mock_blob_props("wiki/concepts/brand-awareness.md"),
        _mock_blob_props("wiki/entities/skillsoft.md"),
    ]

    def _list_blobs(name_starts_with: str = "") -> list:
        return [b for b in blobs if b.name.startswith(name_starts_with)]

    def _download(blob_name: str) -> bytes:
        mapping = {
            "wiki/summaries/marketing-overview.md": summary_content,
            "wiki/concepts/brand-awareness.md": concept_content,
            "wiki/entities/skillsoft.md": entity_content,
        }
        return mapping[blob_name].encode()

    mock_container = MagicMock()
    mock_container.list_blobs.side_effect = _list_blobs
    mock_blob_client = MagicMock()
    mock_blob_client.download_blob.return_value.readall.side_effect = (
        lambda: _download(mock_blob_client._blob_name)
    )

    uploaded_content: list[bytes] = []

    def _get_blob_client(name: str) -> MagicMock:
        bc = MagicMock()
        bc._blob_name = name
        if name != "wiki/index.md":
            bc.download_blob.return_value.readall.return_value = _download(name)
        else:
            bc.upload_blob.side_effect = lambda data, **_: uploaded_content.append(data)
        return bc

    mock_container.get_blob_client.side_effect = _get_blob_client
    client._service.get_container_client.return_value = mock_container

    client.rebuild_and_upload_index("kb-test-container")

    assert uploaded_content, "index.md should have been uploaded"
    index_text = uploaded_content[0].decode("utf-8")
    assert "## Documents" in index_text
    assert "## Concepts" in index_text
    assert "## Entities" in index_text
    assert "Marketing Overview" in index_text
    assert "Brand Awareness" in index_text
    assert "Skillsoft" in index_text


def test_rebuild_and_upload_index_empty_kb() -> None:
    """rebuild_and_upload_index handles a KB with no wiki blobs (T030b)."""
    client = _make_blob_client(_make_config())

    uploaded_content: list[bytes] = []

    mock_container = MagicMock()
    mock_container.list_blobs.return_value = iter([])
    index_bc = MagicMock()
    index_bc.upload_blob.side_effect = lambda data, **_: uploaded_content.append(data)
    mock_container.get_blob_client.return_value = index_bc
    client._service.get_container_client.return_value = mock_container

    client.rebuild_and_upload_index("kb-empty")

    assert uploaded_content, "index.md should still be uploaded for an empty KB"
    index_text = uploaded_content[0].decode("utf-8")
    assert "# Knowledge Base Index" in index_text
