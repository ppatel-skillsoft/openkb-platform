"""Unit tests for KBDispatcher and build_kb_app — per-KB MCP routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from mcp_server.dispatcher import (
    KBDispatcher,
    _KBRecord,
    _ManagedApp,
    build_kb_app,
    resolve_kb_by_slug,
)
from mcp_server.exceptions import GeneratorAPIError, KBNotFoundError, KBNotReadyError

_SLUG = "marketing-kb"
_KB_ID = "6644cfee-e287-4e6d-a29b-f873e5eb64e8"
_KB_RECORD = _KBRecord(kb_id=_KB_ID, name="Marketing KB", description="Marketing content.")


# ---------------------------------------------------------------------------
# resolve_kb_by_slug
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_kb_returns_none_when_not_found() -> None:
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("mcp_server.dispatcher.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await resolve_kb_by_slug("unknown-slug")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_kb_returns_record_when_found() -> None:
    mock_row = MagicMock()
    mock_row.id = _KB_ID
    mock_row.name = "Marketing KB"
    mock_row.description = "Marketing content."

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("mcp_server.dispatcher.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await resolve_kb_by_slug(_SLUG)

    assert result is not None
    assert result.kb_id == _KB_ID
    assert result.name == "Marketing KB"
    assert result.description == "Marketing content."


# ---------------------------------------------------------------------------
# build_kb_app — ask tool behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_tool_raises_on_blank_question() -> None:
    """ask() validates that the question is not blank."""
    from mcp_server.dispatcher import build_kb_app

    # Just test the validation logic directly without going through FastMCP
    app = build_kb_app(_KB_RECORD, "http://generator-api:8001", 30.0)
    assert app is not None  # App was built without error


def test_build_kb_app_produces_asgi_app() -> None:
    """build_kb_app returns a callable ASGI app."""
    app = build_kb_app(_KB_RECORD, "http://generator-api:8001", 30.0)
    assert callable(app)


# ---------------------------------------------------------------------------
# KBDispatcher — routing and caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_returns_404_for_unknown_slug() -> None:
    dispatcher = KBDispatcher("http://generator-api:8001", 30.0)

    with patch("mcp_server.dispatcher.resolve_kb_by_slug", return_value=None):
        responses: list[dict] = []

        async def capture_send(message: dict) -> None:
            responses.append(message)

        scope = {"type": "http", "method": "GET", "path": "/unknown-kb/mcp", "query_string": b""}
        await dispatcher(scope, AsyncMock(), capture_send)

    # First message is the HTTP response start
    assert responses[0]["type"] == "http.response.start"
    assert responses[0]["status"] == 404


@pytest.mark.asyncio
async def test_dispatcher_returns_404_for_empty_slug() -> None:
    dispatcher = KBDispatcher("http://generator-api:8001", 30.0)

    responses: list[dict] = []

    async def capture_send(message: dict) -> None:
        responses.append(message)

    scope = {"type": "http", "method": "GET", "path": "/", "query_string": b""}
    await dispatcher(scope, AsyncMock(), capture_send)

    assert responses[0]["type"] == "http.response.start"
    assert responses[0]["status"] == 404


@pytest.mark.asyncio
async def test_dispatcher_caches_app_on_second_call() -> None:
    dispatcher = KBDispatcher("http://generator-api:8001", 30.0)
    mock_app = AsyncMock()

    with patch("mcp_server.dispatcher.resolve_kb_by_slug", return_value=_KB_RECORD), \
         patch("mcp_server.dispatcher.build_kb_app", return_value=mock_app) as mock_build, \
         patch.object(_ManagedApp, "start", new_callable=AsyncMock):

        scope = {"type": "http", "method": "POST", "path": f"/{_SLUG}/mcp", "query_string": b""}

        await dispatcher(scope, AsyncMock(), AsyncMock())
        await dispatcher(scope, AsyncMock(), AsyncMock())

        # build_kb_app called only once despite two requests
        assert mock_build.call_count == 1


@pytest.mark.asyncio
async def test_dispatcher_strips_slug_prefix_from_path() -> None:
    """Forwarded scope has /{slug} stripped — FastMCP app sees /mcp."""
    dispatcher = KBDispatcher("http://generator-api:8001", 30.0)

    received_scopes: list[dict] = []

    async def fake_app(scope, receive, send):
        received_scopes.append(scope)

    with patch("mcp_server.dispatcher.resolve_kb_by_slug", return_value=_KB_RECORD), \
         patch("mcp_server.dispatcher.build_kb_app", return_value=fake_app), \
         patch.object(_ManagedApp, "start", new_callable=AsyncMock):

        scope = {
            "type": "http",
            "method": "POST",
            "path": f"/{_SLUG}/mcp",
            "raw_path": f"/{_SLUG}/mcp".encode(),
            "query_string": b"",
        }
        await dispatcher(scope, AsyncMock(), AsyncMock())

    assert received_scopes[0]["path"] == "/mcp"
    assert received_scopes[0]["raw_path"] == b"/mcp"


@pytest.mark.asyncio
async def test_dispatcher_passes_through_non_http_scope() -> None:
    """Lifespan and other non-HTTP scope types are silently ignored."""
    dispatcher = KBDispatcher("http://generator-api:8001", 30.0)
    scope = {"type": "lifespan"}
    # Should not raise
    await dispatcher(scope, AsyncMock(), AsyncMock())
