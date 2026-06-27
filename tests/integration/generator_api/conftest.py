from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest_asyncio
from httpx import ASGITransport

# Provide required env vars before any generator_api import so that
# Settings can be constructed during the lifespan without touching real infra.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1",
)


@pytest_asyncio.fixture
async def client():
    """Return an AsyncClient wired to the generator_api FastAPI app.

    The Postgres and Azurite lifespan checks are patched to succeed so no
    real infrastructure is needed.  ``get_db`` is overridden to yield a
    plain ``AsyncMock`` session — service functions are mocked per-test so
    the session is never actually used.
    """
    from generator_api.app import app
    from generator_api.config import Settings, get_settings
    from generator_api.db import get_db

    mock_settings = MagicMock(spec=Settings)
    mock_settings.azure_storage_connection_string = "fake-conn-str"
    mock_settings.llm_api_key = ""
    mock_settings.generator_request_timeout = 30

    async def _fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_settings] = lambda: mock_settings

    with (
        patch("generator_api.app.check_postgres", new=AsyncMock(return_value="ok")),
        patch("generator_api.app.check_azurite", new=AsyncMock(return_value="ok")),
        patch("generator_api.app.get_settings", return_value=mock_settings),
    ):
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

    app.dependency_overrides.clear()
