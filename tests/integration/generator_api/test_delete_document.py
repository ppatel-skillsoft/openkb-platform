from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from generator_api.exceptions import DocumentNotFoundError, KBNotFoundError

_KB_ID = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
_DOC_ID = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
_URL = f"/kbs/{_KB_ID}/documents/{_DOC_ID}"
_SVC = "generator_api.router.service_delete_document"


@pytest.mark.asyncio
async def test_delete_returns_204(client) -> None:
    """DELETE with valid UUIDs and successful service call returns 204."""
    with patch(_SVC, new_callable=AsyncMock, return_value=None):
        resp = await client.delete(_URL)
    assert resp.status_code == 204
    assert resp.content == b""


@pytest.mark.asyncio
async def test_delete_idempotent_204(client) -> None:
    """Two DELETE calls both return 204 (service handles idempotency)."""
    with patch(_SVC, new_callable=AsyncMock, return_value=None):
        r1 = await client.delete(_URL)
        r2 = await client.delete(_URL)
    assert r1.status_code == 204
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_delete_kb_not_found_404(client) -> None:
    """KBNotFoundError from service layer → 404 with detail."""
    with patch(_SVC, new_callable=AsyncMock, side_effect=KBNotFoundError(_KB_ID)):
        resp = await client.delete(_URL)
    assert resp.status_code == 404
    assert _KB_ID in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_doc_not_found_404(client) -> None:
    """DocumentNotFoundError from service layer → 404 with detail."""
    with patch(_SVC, new_callable=AsyncMock, side_effect=DocumentNotFoundError(_DOC_ID, _KB_ID)):
        resp = await client.delete(_URL)
    assert resp.status_code == 404
    assert _DOC_ID in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_invalid_uuid_422(client) -> None:
    """Non-UUID path parameter → FastAPI returns 422 Unprocessable Entity."""
    resp = await client.delete("/kbs/not-a-uuid/documents/also-not-a-uuid")
    assert resp.status_code == 422

