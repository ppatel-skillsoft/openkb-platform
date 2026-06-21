from __future__ import annotations

"""Alembic async environment for OpenKB migrations."""

import asyncio
import logging
import os
import ssl as ssl_module
from logging.config import fileConfig
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from alembic import context
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from openkb.db.metadata import metadata

load_dotenv()

logger = logging.getLogger("alembic.env")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Copy .env.example to .env and fill in the connection string."
        )
    return url


def _extract_ssl_connect_args(url: str) -> tuple[str, dict]:
    """Strip ssl/sslmode from URL and return connect_args for asyncpg."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    sslmode = params.pop("sslmode", [None])[0] or params.pop("ssl", [None])[0]

    if sslmode in ("require", "verify-ca", "verify-full", "true", "True", "1"):
        ctx = ssl_module.create_default_context()
        ssl_value: bool | ssl_module.SSLContext = ctx
    else:
        ssl_value = False

    clean_query = urlencode({k: v[0] for k, v in params.items()})
    clean_url = urlunparse(parsed._replace(query=clean_query))
    return clean_url, {"ssl": ssl_value}


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required)."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode via the async engine."""
    raw_url = get_database_url()
    url, connect_args = _extract_ssl_connect_args(raw_url)
    connectable = create_async_engine(url, echo=False, connect_args=connect_args)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
