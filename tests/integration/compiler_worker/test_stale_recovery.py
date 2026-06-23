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
    # Commit so _recover_stale (which uses the singleton engine) can see the rows.
    await async_db_session.commit()

    # Run stale recovery directly
    import os

    from compiler_worker.config import WorkerConfig
    from compiler_worker.worker import WorkerLoop

    config = WorkerConfig(
        database_url=os.environ["DATABASE_URL"],
        blob_connection_string=os.environ["AZURE_STORAGE_CONNECTION_STRING"],
        sidecar_cmd="echo",
        kb_id=kb_id,
    )

    loop = WorkerLoop(config)
    await loop._recover_stale()

    # Re-read via a fresh query (expire session cache after external update)
    async_db_session.expire_all()

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

    # Cleanup committed rows
    from openkb.db import knowledge_bases
    from sqlalchemy import delete
    await async_db_session.execute(delete(documents).where(documents.c.kb_id == kb_id))
    await async_db_session.execute(delete(knowledge_bases).where(knowledge_bases.c.id == kb_id))
    await async_db_session.commit()
