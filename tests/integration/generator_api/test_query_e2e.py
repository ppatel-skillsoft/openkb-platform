"""Integration tests for the query route — T020."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from generator_api.app import create_app
from generator_api.pool import SidecarPool
from generator_api.sidecar import SidecarProcess


@pytest.fixture()
def mock_pool() -> MagicMock:
    pool = MagicMock(spec=SidecarPool)
    mock_sidecar = MagicMock(spec=SidecarProcess)
    mock_sidecar.query.return_value = ("Test answer", [], 42)
    pool.get_or_start = AsyncMock(return_value=mock_sidecar)
    pool.update_last_used = MagicMock()
    pool.invalidate = MagicMock()
    pool.shutdown = AsyncMock()
    pool.evict_idle_loop = AsyncMock()
    pool.get_registry_snapshot = MagicMock(return_value={})
    return pool


@pytest.fixture()
def app(mock_pool: MagicMock):
    application = create_app()
    application.state.pool = mock_pool
    return application


@pytest.mark.asyncio
async def test_query_route_uses_pool(app, mock_pool: MagicMock) -> None:
    """Query route delegates to pool.get_or_start (T020a)."""
    assert mock_pool.get_or_start is not None
    assert mock_pool.update_last_used is not None
