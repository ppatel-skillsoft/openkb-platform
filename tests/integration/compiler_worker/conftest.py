from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def worker_config():
    """Return a ``WorkerConfig`` loaded from the test environment."""
    from compiler_worker.config import WorkerConfig
    return WorkerConfig.from_env()


@pytest_asyncio.fixture
async def async_db_session():
    """Yield an async DB session connected to the real test database.

    Creates a dedicated engine per test to avoid connection pool state leaking
    across function-scoped event loops (pytest-asyncio asyncio_mode=auto).
    Uses openkb-core's _extract_ssl_connect_args to strip asyncpg-incompatible
    sslmode query parameters from the DATABASE_URL.
    """
    import os
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from openkb.db.engine import _extract_ssl_connect_args

    raw_url = os.environ.get("DATABASE_URL", "")
    url, connect_args = _extract_ssl_connect_args(raw_url)
    engine = create_async_engine(url, echo=False, connect_args=connect_args)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def blob_client(worker_config):
    """Return a ``BlobStorageClient`` pointed at Azurite."""
    from compiler_worker.blob_client import BlobStorageClient
    return BlobStorageClient(worker_config.blob_connection_string)


@pytest_asyncio.fixture
async def seed_kb(async_db_session):
    """Insert a knowledge_bases row and clean up after the test."""
    from openkb.db import knowledge_bases

    kb_id = str(uuid.uuid4())
    container = f"kb-{kb_id}"
    await async_db_session.execute(
        knowledge_bases.insert().values(
            id=kb_id,
            name="Test KB",
            slug=f"test-{kb_id[:8]}",
            storage_container_path=container,
            compilation_config={"model": "gpt-4o-mini", "language": "en"},
            status="active",
        )
    )
    await async_db_session.flush()
    yield {"kb_id": kb_id, "container": container}
    # Cleanup handled by transaction rollback in tests


@pytest_asyncio.fixture
async def seed_document(async_db_session, seed_kb):
    """Insert a documents row with status 'pending'."""
    from openkb.db import documents

    doc_id = str(uuid.uuid4())
    kb_id = seed_kb["kb_id"]
    blob_path = f"{seed_kb['container']}/raw/test-doc.md"
    await async_db_session.execute(
        documents.insert().values(
            id=doc_id,
            kb_id=kb_id,
            source_type="md",
            source_uri=blob_path,
            original_filename="test-doc.md",
            status="pending",
        )
    )
    await async_db_session.flush()
    yield {
        "doc_id": doc_id,
        "kb_id": kb_id,
        "blob_path": blob_path,
        "filename": "test-doc.md",
    }
