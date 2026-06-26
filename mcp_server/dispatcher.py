"""Per-KB ASGI dispatcher for the MCP server.

Routes ``/{kb_slug}/mcp`` to a lazily-created, cached FastMCP instance
scoped to that KB.  Each FastMCP instance exposes exactly one tool —
``ask(question)`` — with ``kb_id`` captured in a closure so it is never
exposed to the LLM.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import text
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from mcp_server.db import get_session
from mcp_server.exceptions import GeneratorAPIError, KBNotFoundError, KBNotReadyError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _KBRecord:
    kb_id: str
    name: str
    description: str | None


# ---------------------------------------------------------------------------
# KB resolution
# ---------------------------------------------------------------------------

_RESOLVE_QUERY = text(
    """
    SELECT kb.id::text AS id, kb.name, kb.description
    FROM   knowledge_bases kb
    WHERE  kb.slug = :slug
      AND  kb.deleted_at IS NULL
      AND  EXISTS (
               SELECT 1
               FROM   documents d
               WHERE  d.kb_id     = kb.id
                 AND  d.status    = 'complete'
                 AND  d.deleted_at IS NULL
           )
    LIMIT  1
    """
)


async def resolve_kb_by_slug(slug: str) -> _KBRecord | None:
    """Return KB metadata for *slug*, or ``None`` if not found / no compiled docs."""
    async with get_session() as session:
        result = await session.execute(_RESOLVE_QUERY, {"slug": slug})
        row = result.fetchone()
    if row is None:
        return None
    return _KBRecord(kb_id=row.id, name=row.name, description=row.description)


# ---------------------------------------------------------------------------
# Per-KB FastMCP app factory
# ---------------------------------------------------------------------------


def build_kb_app(
    kb: _KBRecord,
    generator_api_url: str,
    query_timeout_s: float,
) -> Any:
    """Build and return a Starlette ASGI app (FastMCP) scoped to *kb*."""

    # Capture in closure — never exposed as a tool parameter
    kb_id = kb.kb_id
    kb_name = kb.name

    @asynccontextmanager
    async def _lifespan(server: FastMCP):
        async with httpx.AsyncClient(
            base_url=generator_api_url,
            timeout=httpx.Timeout(query_timeout_s),
        ) as client:
            yield {"http_client": client}

    instructions = f"You are connected to the '{kb_name}' knowledge base."
    if kb.description:
        instructions += f" {kb.description}"
    instructions += (
        " Use the ask tool to get grounded answers with citations from the knowledge base."
    )

    mcp = FastMCP(kb_name, instructions=instructions, lifespan=_lifespan)

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def ask(question: str, ctx: Context) -> str:
        """Ask a natural-language question and get a grounded answer with citations.

        Args:
            question: Natural-language question about the knowledge base (1–8000 chars).
        """
        stripped = question.strip()
        if not stripped:
            raise ValueError("question must not be blank")
        if len(stripped) > 8000:
            raise ValueError("question must be 8000 characters or fewer")

        client: httpx.AsyncClient = ctx.lifespan_context["http_client"]
        logger.info("ask kb_id=%s question_length=%d", kb_id, len(stripped))

        try:
            resp = await client.post(
                f"/kbs/{kb_id}/query",
                json={"question": stripped},
            )
        except httpx.TimeoutException as exc:
            raise GeneratorAPIError(
                "Request to generator-api timed out", status_code=504
            ) from exc
        except httpx.RequestError as exc:
            raise GeneratorAPIError(
                f"Could not reach generator-api: {exc}", status_code=503
            ) from exc

        if resp.status_code == 404:
            raise KBNotFoundError(kb_id)
        if resp.status_code == 409:
            raise KBNotReadyError(kb_id)
        if resp.status_code >= 500 or not resp.is_success:
            raise GeneratorAPIError(
                f"generator-api returned {resp.status_code}",
                status_code=resp.status_code,
            )

        data = resp.json()
        answer: str = data.get("answer", "")
        citations: list[Any] = data.get("citations", [])

        if citations:
            formatted = "\n".join(f"- {c}" for c in citations)
            answer = f"{answer}\n\n**Sources:**\n{formatted}"

        return answer

    return mcp.http_app(path="/mcp")


# ---------------------------------------------------------------------------
# Dispatcher ASGI app
# ---------------------------------------------------------------------------


class KBDispatcher:
    """ASGI app that routes ``/{kb_slug}/mcp[/...]`` to per-KB FastMCP instances.

    On first request for a slug the dispatcher resolves the KB from Postgres,
    builds a FastMCP app for it, and caches the result.  Subsequent requests
    hit the cache directly.

    Unknown slugs or slugs with no compiled documents return HTTP 404.
    """

    def __init__(self, generator_api_url: str, query_timeout_s: float) -> None:
        self._generator_api_url = generator_api_url
        self._query_timeout_s = query_timeout_s
        self._apps: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def _get_or_create(self, slug: str) -> Any | None:
        if slug in self._apps:
            return self._apps[slug]
        async with self._lock:
            if slug in self._apps:
                return self._apps[slug]
            kb = await resolve_kb_by_slug(slug)
            if kb is None:
                return None
            app = build_kb_app(kb, self._generator_api_url, self._query_timeout_s)
            self._apps[slug] = app
            logger.info("Registered MCP app for kb_slug=%s name=%r", slug, kb.name)
            return app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return

        path: str = scope.get("path", "/")
        parts = path.lstrip("/").split("/", 1)
        slug = parts[0]
        rest = "/" + parts[1] if len(parts) > 1 else "/"

        if not slug:
            await JSONResponse(
                {"error": "No KB slug provided. Connect to /{kb_slug}/mcp"},
                status_code=404,
            )(scope, receive, send)
            return

        app = await self._get_or_create(slug)
        if app is None:
            await JSONResponse(
                {
                    "error": (
                        f"Knowledge base '{slug}' not found or has no compiled documents"
                    )
                },
                status_code=404,
            )(scope, receive, send)
            return

        # Strip the /{slug} prefix so the FastMCP app sees /mcp/...
        new_scope = dict(scope)
        new_scope["path"] = rest
        new_scope["raw_path"] = rest.encode()
        await app(new_scope, receive, send)
