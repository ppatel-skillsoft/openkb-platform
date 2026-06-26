from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from mcp_server.exceptions import GeneratorAPIError
from mcp_server.tools.list_kbs import KBSummary, list_kbs

logger = logging.getLogger(__name__)


def _make_row(id: str, name: str, document_count: int) -> MagicMock:
    row = MagicMock()
    row.id = id
    row.name = name
    row.document_count = document_count
    return row


@pytest.mark.asyncio
async def test_list_kbs_empty_returns_empty_list() -> None:
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ctx = MagicMock()

    with patch("mcp_server.tools.list_kbs.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_kbs(ctx)

    assert result == []


@pytest.mark.asyncio
async def test_list_kbs_two_rows_returns_two_summaries() -> None:
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        _make_row("aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa", "Marketing KB", 5),
        _make_row("bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb", "Sales KB", 3),
    ]

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ctx = MagicMock()

    with patch("mcp_server.tools.list_kbs.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_kbs(ctx)

    assert len(result) == 2
    assert isinstance(result[0], KBSummary)
    assert result[0].id == "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    assert result[0].name == "Marketing KB"
    assert result[0].document_count == 5
    assert result[0].ready is True
    assert result[1].id == "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"
    assert result[1].name == "Sales KB"
    assert result[1].document_count == 3
    assert result[1].ready is True


@pytest.mark.asyncio
async def test_list_kbs_ready_always_true() -> None:
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        _make_row("cccccccc-cccc-4ccc-cccc-cccccccccccc", "Test KB", 1),
    ]

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    ctx = MagicMock()

    with patch("mcp_server.tools.list_kbs.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await list_kbs(ctx)

    assert result[0].ready is True


@pytest.mark.asyncio
async def test_list_kbs_sqlalchemy_error_raises_generator_api_error() -> None:
    mock_session = AsyncMock()
    mock_session.execute.side_effect = SQLAlchemyError("connection refused")

    ctx = MagicMock()

    with patch("mcp_server.tools.list_kbs.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(GeneratorAPIError, match="Database error"):
            await list_kbs(ctx)
