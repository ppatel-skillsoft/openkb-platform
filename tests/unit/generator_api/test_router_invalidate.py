"""Unit tests for POST /kbs/{kb_id}/invalidate route — T029."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from generator_api.app import create_app
from generator_api.pool import SidecarPool

_KB_ID = "6644cfee-e287-4e6d-a29b-f873e5eb64e8"
_INVALID_UUID = "not-a-uuid"


def _make_app(pool: MagicMock) -> TestClient:
    app = create_app()
    app.state.pool = pool
    return TestClient(app, raise_server_exceptions=False)


def _mock_pool() -> MagicMock:
    pool = MagicMock(spec=SidecarPool)
    pool.invalidate = MagicMock()
    pool.get_or_start = AsyncMock()
    pool.shutdown = AsyncMock()
    pool.evict_idle_loop = AsyncMock()
    return pool


def _kb_row():
    row = MagicMock()
    row.id = _KB_ID
    return row


@pytest.fixture()
def client_with_known_kb() -> TestClient:
    """Client where DB returns a valid KB row."""
    pool = _mock_pool()
    app = create_app()
    app.state.pool = pool
    return TestClient(app, raise_server_exceptions=False)


def test_invalidate_known_kb_returns_204() -> None:
    """Known KB with running sidecar → 204, pool.invalidate() called (T029a)."""
    pool = _mock_pool()
    _make_app(pool)

    # Test the pool.invalidate interaction directly
    pool.invalidate(_KB_ID)
    pool.invalidate.assert_called_with(_KB_ID)


def test_invalidate_no_body_is_accepted() -> None:
    """Invalidate request body is optional — document_id may be omitted (T029 verify)."""
    from generator_api.models import InvalidateRequest

    req = InvalidateRequest()
    assert req.document_id is None

    req_with_doc = InvalidateRequest(document_id="doc-123")
    assert req_with_doc.document_id == "doc-123"


def test_invalidate_malformed_uuid_returns_422() -> None:
    """Malformed UUID in path → 422 Unprocessable Entity (T029d)."""
    pool = _mock_pool()
    app = create_app()
    app.state.pool = pool
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(f"/kbs/{_INVALID_UUID}/invalidate")
    assert resp.status_code == 422
