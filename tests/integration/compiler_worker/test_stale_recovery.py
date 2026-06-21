from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_stale_recovery_marks_compiling_as_failed(async_db_session, seed_kb):
    """Startup recovery sets all 'compiling' docs to 'failed' for the scoped KB."""
    from openkb.db import documents
    from sqlalchemy import select, text
    from compiler_worker.worker import WorkerLoop
    from compiler_worker.config import WorkerConfig

    kb_id = seed_kb["kb_id"]

    # Insert 3 stale documents (status='compiling')
    stale_ids = []
    for _ in range(3):
        doc_id = str(uuid.uuid4())
        await async_db_session.execute(
            documents.insert().values(
                id=doc_id,
                kb_id=kb_id,
                source_type="md",
                status="compiling",
            )
        )
        stale_ids.append(doc_id)

    # Insert 1 pending document (should be untouched)
    pending_id = str(uuid.uuid4())
    await async_db_session.execute(
        documents.insert().values(
            id=pending_id,
            kb_id=kb_id,
            source_type="md",
            status="pending",
        )
    )
    await async_db_session.flush()

    # Run stale recovery directly
    import asyncio
    from compiler_worker.worker import WorkerLoop

    # We need a minimal config; only database_url matters here
    import os
    from dataclasses import dataclass

    config_env = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", "postgresql+asyncpg://openkb:openkb@localhost:5433/openkb"),
        "REDIS_URL": os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        "AZURE_STORAGE_CONNECTION_STRING": os.environ.get(
            "AZURE_STORAGE_CONNECTION_STRING", "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=x;BlobEndpoint=http://localhost:10000/devstoreaccount1"
        ),
        "SIDECAR_CMD": "echo",
        "KB_ID": kb_id,
    }
    for k, v in config_env.items():
        os.environ.setdefault(k, v)

    from compiler_worker.config import WorkerConfig
    config = WorkerConfig(
        database_url=config_env["DATABASE_URL"],
        redis_url=config_env["REDIS_URL"],
        blob_connection_string=config_env["AZURE_STORAGE_CONNECTION_STRING"],
        sidecar_cmd="echo",
        kb_id=kb_id,
    )

    loop = WorkerLoop(config)
    await loop._recover_stale()

    # All 3 stale docs should now be 'failed'
    for doc_id in stale_ids:
        row = (
            await async_db_session.execute(
                select(documents).where(documents.c.id == doc_id)
            )
        ).fetchone()
        assert row.status == "failed", f"Expected failed for {doc_id}, got {row.status}"
        assert row.failure_reason and "restarted" in row.failure_reason.lower()

    # Pending doc should be untouched
    pending_row = (
        await async_db_session.execute(
            select(documents).where(documents.c.id == pending_id)
        )
    ).fetchone()
    assert pending_row.status == "pending"
