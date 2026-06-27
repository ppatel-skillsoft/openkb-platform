from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from generator_api.exceptions import DocumentNotFoundError, KBNotFoundError

_KB_ID = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
_DOC_ID = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
_CONN = "fake-conn-str"
_CONTAINER = "kb-aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
_SLUG = "my-document"


def _make_kb_row(container: str | None = None) -> MagicMock:
    row = MagicMock()
    row.id = _KB_ID
    row.slug = "test-kb"
    row.storage_container_path = container
    return row


def _make_doc_row(deleted_at=None) -> MagicMock:
    row = MagicMock()
    row.id = _DOC_ID
    row.slug = _SLUG
    row.deleted_at = deleted_at
    return row


def _make_db(kb_row=None, doc_row=None) -> AsyncMock:
    """Build an AsyncSession mock returning kb_row then doc_row on execute()."""
    db = AsyncMock()
    db.commit = AsyncMock()

    kb_result = MagicMock()
    kb_result.one_or_none.return_value = kb_row

    doc_result = MagicMock()
    doc_result.one_or_none.return_value = doc_row

    db.execute = AsyncMock(side_effect=[kb_result, doc_result, AsyncMock()])
    return db


@pytest.mark.asyncio
async def test_delete_success() -> None:
    """Happy path: doc deleted, summary blob removed, index rebuilt."""
    db = _make_db(kb_row=_make_kb_row(), doc_row=_make_doc_row())

    with (
        patch("generator_api.service.delete_summary_blob", new_callable=AsyncMock) as mock_del,
        patch("generator_api.service.sync_wiki_tree", new_callable=AsyncMock),
        patch("generator_api.service.rebuild_index_md"),
        patch("generator_api.service.upload_index_to_blob", new_callable=AsyncMock) as mock_up,
    ):
        from generator_api.service import service_delete_document
        await service_delete_document(_KB_ID, _DOC_ID, db, _CONN)

    mock_del.assert_awaited_once_with(_CONN, _CONTAINER, _SLUG)
    mock_up.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_idempotent() -> None:
    """Already-deleted doc: no blob ops, no UPDATE, returns None."""
    deleted_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    db = _make_db(kb_row=_make_kb_row(), doc_row=_make_doc_row(deleted_at=deleted_ts))

    with (
        patch("generator_api.service.delete_summary_blob", new_callable=AsyncMock) as mock_del,
        patch("generator_api.service.upload_index_to_blob", new_callable=AsyncMock) as mock_up,
    ):
        from generator_api.service import service_delete_document
        result = await service_delete_document(_KB_ID, _DOC_ID, db, _CONN)

    assert result is None
    mock_del.assert_not_awaited()
    mock_up.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_kb_not_found() -> None:
    """KB row absent → KBNotFoundError raised."""
    db = _make_db(kb_row=None)

    from generator_api.service import service_delete_document
    with pytest.raises(KBNotFoundError) as exc_info:
        await service_delete_document(_KB_ID, _DOC_ID, db, _CONN)
    assert _KB_ID in str(exc_info.value)


@pytest.mark.asyncio
async def test_delete_doc_not_found() -> None:
    """Doc row absent → DocumentNotFoundError raised."""
    db = _make_db(kb_row=_make_kb_row(), doc_row=None)

    from generator_api.service import service_delete_document
    with pytest.raises(DocumentNotFoundError) as exc_info:
        await service_delete_document(_KB_ID, _DOC_ID, db, _CONN)
    assert _DOC_ID in str(exc_info.value)


@pytest.mark.asyncio
async def test_delete_cross_kb_mismatch() -> None:
    """Doc belonging to a different KB returns None from ownership query → DocumentNotFoundError."""
    db = _make_db(kb_row=_make_kb_row(), doc_row=None)

    from generator_api.service import service_delete_document
    with pytest.raises(DocumentNotFoundError):
        await service_delete_document(_KB_ID, _DOC_ID, db, _CONN)


@pytest.mark.asyncio
async def test_delete_blob_already_absent() -> None:
    """delete_summary_blob swallows ResourceNotFoundError — service still rebuilds index."""
    from azure.core.exceptions import ResourceNotFoundError
    db = _make_db(kb_row=_make_kb_row(), doc_row=_make_doc_row())

    with (
        patch("generator_api.service.delete_summary_blob", new_callable=AsyncMock) as mock_del,
        patch("generator_api.service.sync_wiki_tree", new_callable=AsyncMock),
        patch("generator_api.service.rebuild_index_md"),
        patch("generator_api.service.upload_index_to_blob", new_callable=AsyncMock) as mock_up,
    ):
        # delete_summary_blob itself swallows ResourceNotFoundError internally,
        # so we model it as returning normally here.
        mock_del.return_value = None

        from generator_api.service import service_delete_document
        await service_delete_document(_KB_ID, _DOC_ID, db, _CONN)

    mock_up.assert_awaited_once()

