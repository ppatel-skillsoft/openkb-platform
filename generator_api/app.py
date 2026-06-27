"""FastAPI application factory for the Generator API."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from generator_api import __version__
from generator_api.blob import check_azurite
from generator_api.config import get_settings
from generator_api.db import check_postgres
from generator_api.exceptions import (
    BlobSyncError,
    DocumentNotFoundError,
    KBNotFoundError,
    KBNotReadyError,
    SidecarQueryError,
    SidecarStartError,
)
from generator_api.models import HealthResponse
from generator_api.pool import SidecarPool

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = get_settings()

    if not settings.llm_api_key:
        logger.warning(
            "LLM_API_KEY is not set — service will start but queries will fail at the LLM level"
        )

    pg_status = await check_postgres()
    if pg_status != "ok":
        raise RuntimeError(f"Postgres unreachable at startup: {pg_status}")

    az_status = await check_azurite(settings.azure_storage_connection_string)
    if az_status != "ok":
        raise RuntimeError(f"Azurite unreachable at startup: {az_status}")

    pool = SidecarPool(settings)
    app.state.pool = pool

    eviction_task = asyncio.create_task(pool.evict_idle_loop())

    logger.info("Generator API v%s starting — all dependencies reachable", __version__)
    yield

    # ── Graceful shutdown ────────────────────────────────────────────────────
    if settings.prewarm_on_startup:
        # Pre-warm runs as a background task after yield; cancel if still running
        pass

    logger.info("Generator API shutting down — terminating all sidecars")
    eviction_task.cancel()
    try:
        await eviction_task
    except asyncio.CancelledError:
        pass
    await pool.shutdown()

    logger.info("Generator API shutdown complete")


def create_app() -> FastAPI:
    from generator_api.router import router

    app = FastAPI(
        title="OpenKB Generator API",
        version=__version__,
        description="Query proxy: serves grounded answers from persistent KB sidecars.",
        lifespan=_lifespan,
    )

    app.include_router(router)

    # ── Health endpoint ──────────────────────────────────────────────────────

    @app.get("/health", tags=["Health"])
    async def health() -> JSONResponse:
        settings = get_settings()
        pg = await check_postgres()
        az = await check_azurite(settings.azure_storage_connection_string)
        all_ok = pg == "ok" and az == "ok"
        body = HealthResponse(
            status="ok" if all_ok else "degraded",
            postgres=pg,
            azurite=az,
            detail=None if all_ok else f"postgres={pg} azurite={az}",
        )
        return JSONResponse(
            status_code=200 if all_ok else 503,
            content=body.model_dump(exclude_none=True),
        )

    # ── Exception handlers ───────────────────────────────────────────────────

    @app.exception_handler(KBNotFoundError)
    async def _kb_not_found(request: Request, exc: KBNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DocumentNotFoundError)
    async def _doc_not_found(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(KBNotReadyError)
    async def _kb_not_ready(request: Request, exc: KBNotReadyError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(BlobSyncError)
    async def _blob_sync_error(request: Request, exc: BlobSyncError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(SidecarStartError)
    async def _sidecar_start(request: Request, exc: SidecarStartError) -> JSONResponse:
        return JSONResponse(
            status_code=502, content={"detail": f"Sidecar failed to start: {exc}"}
        )

    @app.exception_handler(SidecarQueryError)
    async def _sidecar_query(request: Request, exc: SidecarQueryError) -> JSONResponse:
        return JSONResponse(
            status_code=502, content={"detail": f"Sidecar error: {exc}"}
        )

    @app.exception_handler(asyncio.TimeoutError)
    async def _timeout(request: Request, exc: asyncio.TimeoutError) -> JSONResponse:
        settings = get_settings()
        return JSONResponse(
            status_code=504,
            content={
                "detail": f"Query timed out after {settings.generator_request_timeout}s"
            },
        )

    return app


app = create_app()
