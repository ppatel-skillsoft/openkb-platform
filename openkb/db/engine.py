from __future__ import annotations

"""Async database engine and session factory for OpenKB.

Public interface (matches contracts/db-session-factory.md):
    get_engine()      → AsyncEngine      (singleton, lazy-initialised)
    get_session()     → AsyncContextManager[AsyncSession]
    get_connection()  → AsyncContextManager[AsyncConnection]
    ConfigurationError                   (raised when DATABASE_URL is missing)

All callers — compiler-worker, generator-api, seed scripts, tests — import
from here.  No service should manage its own engine or parse DATABASE_URL.
"""

import logging
import os
import re
import ssl as ssl_module
from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

_ASYNCPG_PREFIX = "postgresql+asyncpg://"
_engine: AsyncEngine | None = None


class ConfigurationError(Exception):
    """Raised when DATABASE_URL is missing or not a valid async Postgres URL."""


def _extract_ssl_connect_args(url: str) -> tuple[str, dict]:
    """Parse SSL-related query params from the URL.

    asyncpg does not accept ``sslmode`` as a URL query param via SQLAlchemy.
    Instead we strip ssl/sslmode from the URL ourselves and return the
    appropriate ``connect_args`` dict.

    Returns:
        (clean_url_without_ssl_params, connect_args_dict)

    Mapping:
        sslmode=disable / ssl=false → connect_args={"ssl": False}
        sslmode=require / ssl=require / ssl=true → connect_args={"ssl": <SSLContext>}
        absent → connect_args={"ssl": False}  (safe default for Docker local dev)
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    sslmode = (params.pop("sslmode", [None])[0] or params.pop("ssl", [None])[0])

    if sslmode in ("require", "verify-ca", "verify-full", "true", "True", "1"):
        ctx = ssl_module.create_default_context()
        ssl_value: bool | ssl_module.SSLContext = ctx
    else:
        # disable, allow, prefer, false, absent → no SSL (Docker local dev default)
        ssl_value = False

    clean_query = urlencode({k: v[0] for k, v in params.items()})
    clean_url = urlunparse(parsed._replace(query=clean_query))
    return clean_url, {"ssl": ssl_value}


def get_engine() -> AsyncEngine:
    """Return the singleton AsyncEngine.

    Reads DATABASE_URL from the environment on first call and caches the
    result.  Raises ConfigurationError if the variable is absent or not a
    valid ``postgresql+asyncpg://`` URL.

    Connection errors surface at query time (SQLAlchemy lazy-connect).
    """
    global _engine
    if _engine is not None:
        return _engine

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ConfigurationError(
            "DATABASE_URL environment variable is not set. "
            "Copy .env.example to .env and set a valid connection string."
        )
    if not url.startswith(_ASYNCPG_PREFIX):
        raise ConfigurationError(
            f"DATABASE_URL must start with '{_ASYNCPG_PREFIX}', got: {url!r}. "
            "Only the asyncpg driver is supported."
        )

    url, connect_args = _extract_ssl_connect_args(url)
    _engine = create_async_engine(
        url,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    logger.debug("AsyncEngine created for %s", _redact_url(url))
    return _engine


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding an AsyncSession.

    - Commits automatically on clean exit.
    - Rolls back on any unhandled exception and re-raises.
    - Closes (returns connection to pool) on exit regardless.

    Usage::

        async with get_session() as session:
            result = await session.execute(select(knowledge_bases))
    """
    engine = get_engine()
    _session_factory = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_connection() -> AsyncIterator[AsyncConnection]:
    """Async context manager yielding a raw AsyncConnection.

    Use for DDL, bulk operations, or Core-level queries that don't need a
    session.  The connection is returned to the pool on exit.

    Usage::

        async with get_connection() as conn:
            result = await conn.execute(text("SELECT NOW()"))
    """
    engine = get_engine()
    async with engine.connect() as conn:
        yield conn


def _redact_url(url: str) -> str:
    """Return URL with password replaced by ***."""
    return re.sub(r"(?<=://)([^:]+):([^@]+)@", r"\1:***@", url)


def _reset_engine() -> None:
    """Reset the singleton engine (test helper — do not call in production)."""
    global _engine
    _engine = None
