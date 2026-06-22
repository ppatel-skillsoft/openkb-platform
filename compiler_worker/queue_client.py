from __future__ import annotations

import asyncio
import json
import logging
from typing import Protocol

import sqlalchemy as sa

from compiler_worker.models import CompilationJob
from openkb.db import compiler_jobs, get_engine

logger = logging.getLogger(__name__)


class PostgresQueueClient:
    """Async SKIP LOCKED queue consumer backed by the compiler_jobs Postgres table.

    Uses DELETE … RETURNING for atomic at-most-once claim semantics.
    poll_interval controls sleep between empty-queue polls.
    """

    def __init__(self, poll_interval: float = 2.0) -> None:
        self._poll_interval = poll_interval

    async def dequeue(self, timeout: int) -> str | None:
        """Poll until a job is available or *timeout* seconds elapse.

        Returns a JSON string with the same field names as CompilationJob,
        or None if timeout is reached with no job available.
        """
        engine = get_engine()
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            async with engine.begin() as conn:
                # Atomic claim: delete the oldest pending job and return it.
                row = (
                    await conn.execute(
                        sa.delete(compiler_jobs)
                        .where(
                            compiler_jobs.c.id
                            == sa.select(compiler_jobs.c.id)
                            .where(compiler_jobs.c.status == "pending")
                            .order_by(compiler_jobs.c.enqueued_at)
                            .limit(1)
                            .with_for_update(skip_locked=True)
                            .scalar_subquery()
                        )
                        .returning(
                            compiler_jobs.c.id,
                            compiler_jobs.c.kb_id,
                            compiler_jobs.c.document_id,
                            compiler_jobs.c.blob_path,
                            compiler_jobs.c.filename,
                            compiler_jobs.c.enqueued_at,
                        )
                    )
                ).fetchone()

            if row is not None:
                return json.dumps(
                    {
                        "job_id": str(row.id),
                        "kb_id": str(row.kb_id),
                        "document_id": str(row.document_id),
                        "blob_path": row.blob_path,
                        "filename": row.filename,
                        "enqueued_at": row.enqueued_at.isoformat(),
                    }
                )

            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(self._poll_interval, remaining))

        return None


def parse_job(raw: str) -> CompilationJob | None:
    """Deserialise a raw JSON string into a ``CompilationJob``.

    Returns ``None`` (and logs the error) if the JSON is malformed or any
    required field is missing.  Never raises.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Discarding malformed queue message (invalid JSON): %s — %s", raw, exc)
        return None

    required_fields = ("job_id", "kb_id", "document_id", "blob_path", "filename", "enqueued_at")
    missing = [f for f in required_fields if f not in data]
    if missing:
        logger.error(
            "Discarding queue message with missing fields %s: %s",
            missing,
            raw,
        )
        return None

    return CompilationJob(
        job_id=data["job_id"],
        kb_id=data["kb_id"],
        document_id=data["document_id"],
        blob_path=data["blob_path"],
        filename=data["filename"],
        enqueued_at=data["enqueued_at"],
    )
