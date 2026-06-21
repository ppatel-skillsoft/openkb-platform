from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from openkb import __version__
from openkb.api.deps import get_settings
from openkb.services import (
    KBAlreadyExistsError,
    KBNotFoundError,
    LLMError,
    LockTimeoutError,
    UnsupportedDocumentError,
    URLFetchError,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup validation — fail fast on missing required env vars."""
    settings = get_settings()
    backend = settings.storage_backend

    if backend == "azure":
        missing = []
        if not settings.azure_storage_connection_string:
            missing.append("AZURE_STORAGE_CONNECTION_STRING")
        if not settings.azure_kb_container:
            missing.append("AZURE_KB_CONTAINER")
        if missing:
            raise RuntimeError(
                f"Azure storage backend requires: {', '.join(missing)}. "
                "Check your .env file."
            )
        # Ensure the blob container exists (idempotent — no-op if already present)
        from azure.storage.blob.aio import BlobServiceClient
        from azure.core.exceptions import ResourceExistsError
        async with BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string
        ) as svc:
            try:
                await svc.create_container(settings.azure_kb_container)
                logger.info("Created blob container: %s", settings.azure_kb_container)
            except ResourceExistsError:
                logger.debug("Blob container already exists: %s", settings.azure_kb_container)
    else:
        if not settings.openkb_base_dir.exists():
            settings.openkb_base_dir.mkdir(parents=True, exist_ok=True)

    logger.info("OpenKB API starting — storage backend: %s", backend)
    yield
    logger.info("OpenKB API shutting down")


def create_app() -> FastAPI:
    """FastAPI application factory.

    Import-guarded: only called when ``openkb[api]`` is installed.
    """
    from openkb.api.routes.kb import kb_router  # deferred to avoid import at module level

    app = FastAPI(
        title="OpenKB API",
        version=__version__,
        description="HTTP API for OpenKB — programmatic access to knowledge base operations.",
        lifespan=_lifespan,
    )

    app.include_router(kb_router, prefix="/kb", tags=["Knowledge Base"])

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        return {"status": "ok"}

    # --- Exception handlers ---

    @app.exception_handler(KBNotFoundError)
    async def _kb_not_found(request: Request, exc: KBNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(KBAlreadyExistsError)
    async def _kb_exists(request: Request, exc: KBAlreadyExistsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(LockTimeoutError)
    async def _lock_timeout(request: Request, exc: LockTimeoutError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(LLMError)
    async def _llm_error(request: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(UnsupportedDocumentError)
    async def _unsupported_doc(request: Request, exc: UnsupportedDocumentError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(URLFetchError)
    async def _url_fetch(request: Request, exc: URLFetchError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    return app


# Module-level instance required by uvicorn's `openkb.api.app:app` import string.
app = create_app()
