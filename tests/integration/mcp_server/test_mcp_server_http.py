from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from starlette.testclient import TestClient

logger = logging.getLogger(__name__)

_VALID_KB_ID = "12345678-1234-4234-8234-123456789012"
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _parse_sse_json(text: str) -> dict:
    """Parse the first JSON payload from an SSE response body."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    raise ValueError(f"No data line in SSE response: {text!r}")


def _get_test_app():
    """Build a test http_app with a mocked lifespan (no real DB/HTTP calls)."""
    from contextlib import asynccontextmanager

    from fastmcp import FastMCP
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    from mcp_server.tools.ask_kb import ask_kb
    from mcp_server.tools.list_kbs import list_kbs

    mock_client = AsyncMock(spec=httpx.AsyncClient)

    @asynccontextmanager
    async def _test_lifespan(server: FastMCP):
        yield {"http_client": mock_client}

    test_mcp = FastMCP("OpenKB-test", lifespan=_test_lifespan)
    test_mcp.add_tool(
        FunctionTool.from_function(
            ask_kb,
            annotations=ToolAnnotations(
                readOnlyHint=True, idempotentHint=True, openWorldHint=True
            ),
        )
    )
    test_mcp.add_tool(
        FunctionTool.from_function(
            list_kbs,
            annotations=ToolAnnotations(
                readOnlyHint=True, idempotentHint=True, openWorldHint=False
            ),
        )
    )
    return test_mcp.http_app(path="/mcp"), mock_client


def _mcp_session(client: TestClient) -> str:
    """Initialize an MCP session and return the session ID."""
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers=_MCP_HEADERS,
    )
    assert resp.status_code == 200
    session_id = resp.headers["mcp-session-id"]
    client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers={**_MCP_HEADERS, "mcp-session-id": session_id},
    )
    return session_id


def test_tools_list_contains_ask_kb_and_list_kbs():
    """MCP tools/list endpoint returns both registered tools."""
    http_app, _ = _get_test_app()

    with TestClient(http_app) as client:
        session_id = _mcp_session(client)
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={**_MCP_HEADERS, "mcp-session-id": session_id},
        )
        assert resp.status_code == 200
        body = _parse_sse_json(resp.text)
        tool_names = [t["name"] for t in body["result"]["tools"]]
        assert "ask_kb" in tool_names
        assert "list_kbs" in tool_names


def test_ask_kb_input_schema_has_required_fields():
    """ask_kb inputSchema contains kb_id and question as required properties."""
    http_app, _ = _get_test_app()

    with TestClient(http_app) as client:
        session_id = _mcp_session(client)
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={**_MCP_HEADERS, "mcp-session-id": session_id},
        )
        assert resp.status_code == 200
        body = _parse_sse_json(resp.text)
        tools = {t["name"]: t for t in body["result"]["tools"]}
        ask_schema = tools["ask_kb"]["inputSchema"]
        assert "kb_id" in ask_schema.get("properties", {})
        assert "question" in ask_schema.get("properties", {})


def test_health_route_returns_ok():
    """GET /health returns 200 or 503 with status and generator_api fields."""
    # Use the actual app.py module so the health custom_route is registered
    import mcp_server.app as app_module

    with TestClient(app_module.http_app) as client:
        resp = client.get("/health")
        assert resp.status_code in (200, 503)
        data = resp.json()
        assert "status" in data
        assert "generator_api" in data


def test_ask_kb_call_returns_answer():
    """tools/call ask_kb with valid inputs returns a successful MCP response."""
    http_app, mock_client = _get_test_app()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "answer": "Brand awareness is the primary goal.",
        "citations": [{"source": "brand-overview.md"}],
        "tokens_used": 200,
    }
    mock_client.post.return_value = mock_resp

    with TestClient(http_app) as client:
        session_id = _mcp_session(client)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ask_kb",
                    "arguments": {
                        "kb_id": _VALID_KB_ID,
                        "question": "What is brand awareness?",
                    },
                },
            },
            headers={**_MCP_HEADERS, "mcp-session-id": session_id},
        )
        assert resp.status_code == 200
        body = _parse_sse_json(resp.text)
        assert "result" in body
        assert body["result"]["isError"] is False
        assert len(body["result"]["content"]) > 0


def test_list_kbs_call_returns_list():
    """tools/call list_kbs with mock DB returns a valid MCP response."""
    http_app, _ = _get_test_app()

    mock_row = MagicMock()
    mock_row.id = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    mock_row.name = "Marketing KB"
    mock_row.document_count = 7

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    with patch("mcp_server.tools.list_kbs.get_session") as mock_get_session:
        mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with TestClient(http_app) as client:
            session_id = _mcp_session(client)
            resp = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "list_kbs", "arguments": {}},
                },
                headers={**_MCP_HEADERS, "mcp-session-id": session_id},
            )
            assert resp.status_code == 200
            body = _parse_sse_json(resp.text)
            assert "result" in body
            assert body["result"]["isError"] is False
