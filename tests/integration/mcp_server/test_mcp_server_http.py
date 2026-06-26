from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient

from mcp_server.dispatcher import _KBRecord, build_kb_app

logger = logging.getLogger(__name__)

_KB_RECORD = _KBRecord(
    kb_id="12345678-1234-4234-8234-123456789012",
    name="Test Knowledge Base",
    description=None,
)

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


def test_tools_list_contains_ask():
    """Per-KB FastMCP app exposes exactly one tool: ask."""
    http_app = build_kb_app(_KB_RECORD, "http://generator-api:8001", 30.0)

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
        assert tool_names == ["ask"]


def test_ask_tool_input_schema_has_question_field():
    """ask inputSchema has question as its only required property."""
    http_app = build_kb_app(_KB_RECORD, "http://generator-api:8001", 30.0)

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
        ask_schema = tools["ask"]["inputSchema"]
        assert "question" in ask_schema.get("properties", {})
        # kb_id must NOT be exposed to the LLM
        assert "kb_id" not in ask_schema.get("properties", {})


def test_health_route_returns_ok():
    """GET /health returns 200 or 503 with status and database fields."""
    import asyncio

    import httpx
    from starlette.testclient import TestClient as _TC  # noqa: F401

    import mcp_server.app as app_module

    async def _run():
        with patch("mcp_server.app.check_postgres", new=AsyncMock(return_value="ok")):
            transport = httpx.ASGITransport(app=app_module.http_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/health")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ok"
                assert data["database"] == "ok"

    asyncio.run(_run())


def test_ask_tool_call_returns_answer():
    """tools/call ask with a valid question returns a successful MCP response."""
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_success = True
    mock_resp.json.return_value = {
        "answer": "Brand awareness is the primary goal.",
        "citations": [{"source": "brand-overview.md"}],
        "tokens_used": 200,
    }
    mock_client.post = AsyncMock(return_value=mock_resp)

    from contextlib import asynccontextmanager

    from fastmcp import FastMCP

    @asynccontextmanager
    async def _patched_lifespan(server: FastMCP):
        yield {"http_client": mock_client}

    with patch("mcp_server.dispatcher._make_lifespan", return_value=_patched_lifespan):
        http_app = build_kb_app(_KB_RECORD, "http://generator-api:8001", 30.0)

    with TestClient(http_app) as client:
        session_id = _mcp_session(client)
        resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ask",
                    "arguments": {"question": "What is brand awareness?"},
                },
            },
            headers={**_MCP_HEADERS, "mcp-session-id": session_id},
        )
    assert resp.status_code == 200
    body = _parse_sse_json(resp.text)
    assert "result" in body
    assert body["result"]["isError"] is False
    assert len(body["result"]["content"]) > 0

