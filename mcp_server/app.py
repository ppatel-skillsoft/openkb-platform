"""MCP server ASGI entry point.

Each knowledge base gets its own ``/{kb_slug}/mcp`` endpoint served by a
dedicated FastMCP instance.  ``KBDispatcher`` handles lazy creation and
caching.  The ``/health`` path is intercepted before reaching the dispatcher.
"""

from __future__ import annotations

import logging

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from mcp_server.config import get_settings
from mcp_server.db import check_postgres
from mcp_server.dispatcher import KBDispatcher

logger = logging.getLogger(__name__)

_settings = get_settings()
_dispatcher = KBDispatcher(
    generator_api_url=_settings.generator_api_url,
    query_timeout_s=_settings.query_timeout_s,
)


async def http_app(scope: Scope, receive: Receive, send: Send) -> None:
    """Root ASGI app.

    ``GET /health`` is handled here.  All other paths are forwarded to
    ``KBDispatcher`` which routes ``/{kb_slug}/mcp`` to per-KB FastMCP
    instances.
    """
    if scope["type"] == "http" and scope.get("path") == "/health":
        request = Request(scope, receive)
        if request.method == "GET":
            db_status = await check_postgres()
            overall = "ok" if db_status == "ok" else "degraded"
            status_code = 200 if overall == "ok" else 503
            await JSONResponse(
                {"status": overall, "database": db_status},
                status_code=status_code,
            )(scope, receive, send)
            return

    await _dispatcher(scope, receive, send)
