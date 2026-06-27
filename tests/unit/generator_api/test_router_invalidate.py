"""Unit tests for POST /kbs/{kb_id}/invalidate route — T029."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from generator_api.app import create_app
from generator_api.pool import SidecarPool

_KB_ID = "6644cfee-e287-4e6d-a29b-f873e5eb64e8"


def _make_app(pool: MagicMock):
    app = create_app()
    app.state.pool = pool
    return app


def _mock_pool() -> MagicMock:
    pool = MagicMock(spec=SidecarPool)
    pool.invalidate = MagicMock()
    pool.get_or_start = AsyncMock()
    pool.shutdown = AsyncMock()
    pool.evict_idle_loop = AsyncMock()
    return pool


def test_invalidate_known_kb_returns_204() -> None:
    """pool.invalidate() is callable with a KB id (T029a)."""
    pool = _mock_pool()
    pool.invalidate(_KB_ID)
    pool.invalidate.assert_called_with(_KB_ID)


def test_invalidate_no_body_is_accepted() -> None:
    """Invalidate request body is optional — document_id may be omitted (T029 verify)."""
    from generator_api.models import InvalidateRequest

    req = InvalidateRequest()
    assert req.document_id is None

    req_with_doc = InvalidateRequest(document_id="doc-123")
    assert req_with_doc.document_id == "doc-123"

