from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server.config import get_settings

logger = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _app_lifespan(server: FastMCP):
    """Initialise shared resources for the lifetime of the server process.

    Yields a single ``httpx.AsyncClient`` pointed at ``generator-api``.
    All tool functions retrieve it via ``ctx.lifespan_context["http_client"]``.
    """
    settings = get_settings()
    logger.info(
        "MCP server starting — generator_api_url=%s", settings.generator_api_url
    )
    async with httpx.AsyncClient(
        base_url=settings.generator_api_url,
        timeout=httpx.Timeout(settings.query_timeout_s),
    ) as client:
        yield {"http_client": client}
    logger.info("MCP server shutting down")


# ── FastMCP server instance ───────────────────────────────────────────────────

mcp = FastMCP(
    "OpenKB",
    instructions=(
        "Query compiled knowledge bases. "
        "Use list_kbs to discover available knowledge bases, "
        "then ask_kb to get grounded answers with citations."
    ),
    lifespan=_app_lifespan,
)


# ── Health route ──────────────────────────────────────────────────────────────


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Liveness and dependency health check.

    Pings ``generator-api /health`` using the shared lifespan client.
    Returns HTTP 200 with ``status: ok`` when all upstreams are reachable,
    or HTTP 503 with ``status: degraded`` when any upstream is unavailable.
    This route intentionally bypasses MCP auth so Docker Compose healthchecks
    can reach it without credentials.
    """
    gen_status = "unchecked"
    detail = None

    # Access the lifespan client from the FastMCP server state
    try:
        fastmcp_server = request.app.state.fastmcp_server
        lifespan_ctx = fastmcp_server._lifespan_result
        if lifespan_ctx is None:
            gen_status = "starting"
        else:
            client: httpx.AsyncClient = lifespan_ctx["http_client"]
            resp = await client.get(
                "/health",
                timeout=httpx.Timeout(5.0),
            )
            resp.raise_for_status()
            gen_status = "ok"
    except httpx.HTTPStatusError as exc:
        gen_status = "error"
        detail = f"generator-api returned {exc.response.status_code}"
        logger.warning("generator-api health check failed: %s", exc)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        gen_status = "error"
        detail = str(exc)
        logger.warning("generator-api unreachable: %s", exc)
    except AttributeError:
        # Lifespan context not yet available (e.g. during startup probe)
        gen_status = "starting"

    overall = "ok" if gen_status in ("ok", "unchecked") else "degraded"
    status_code = 200 if overall == "ok" else 503
    return JSONResponse(
        {"status": overall, "generator_api": gen_status, "detail": detail},
        status_code=status_code,
    )


# ── Tool registration — deferred to avoid circular imports ────────────────────
# Tools are registered here after the mcp instance is fully configured.


def _register_tools() -> None:
    from fastmcp.tools import FunctionTool
    from mcp.types import ToolAnnotations

    from mcp_server.tools.ask_kb import ask_kb
    from mcp_server.tools.list_kbs import list_kbs

    mcp.add_tool(
        FunctionTool.from_function(
            ask_kb,
            annotations=ToolAnnotations(
                readOnlyHint=True,
                idempotentHint=True,
                openWorldHint=True,
            ),
        )
    )
    mcp.add_tool(
        FunctionTool.from_function(
            list_kbs,
            annotations=ToolAnnotations(
                readOnlyHint=True,
                idempotentHint=True,
                openWorldHint=False,
            ),
        )
    )


_register_tools()


# ── ASGI application ──────────────────────────────────────────────────────────
# ``http_app`` is the module-level ASGI app referenced by uvicorn:
#   uvicorn mcp_server.app:http_app

http_app = mcp.http_app(path="/mcp")
