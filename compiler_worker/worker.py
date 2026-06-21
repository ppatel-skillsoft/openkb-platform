from __future__ import annotations

import asyncio
import logging
import signal

from compiler_worker.blob_client import BlobStorageClient
from compiler_worker.config import WorkerConfig
from compiler_worker.job import process_job
from compiler_worker.queue_client import RedisQueueClient, parse_job
from openkb.db import documents, get_session
from sqlalchemy import select, text, update

logger = logging.getLogger(__name__)


class WorkerLoop:
    """Main worker loop: dequeues jobs from Redis and processes them one at a time."""

    def __init__(self, config: WorkerConfig) -> None:
        self._config = config
        self._shutdown = False

    def run(self) -> None:
        """Configure logging, run stale recovery, then enter the BRPOP loop.

        Handles SIGTERM and SIGINT gracefully by setting the shutdown flag so the
        loop exits cleanly after the current job completes (or the next idle
        poll timeout).
        """
        logging.basicConfig(
            level=self._config.log_level,
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        )
        logger.info("Worker started — polling %s", self._config.queue_key)

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Stale recovery before entering the poll loop
        asyncio.run(self._recover_stale())

        queue = RedisQueueClient(self._config.redis_url, self._config.queue_key)
        blob_client = BlobStorageClient(self._config.blob_connection_string)

        while not self._shutdown:
            raw = queue.dequeue(self._config.queue_poll_timeout)
            if raw is None:
                logger.debug("No job in queue; polling again")
                continue

            job = parse_job(raw)
            if job is None:
                continue

            logger.info("Dequeued job %s for document %s", job.job_id, job.document_id)
            try:
                asyncio.run(self._run_job(job, blob_client))
            except Exception:
                logger.exception("Unhandled error processing job %s — worker continues", job.job_id)

        logger.info("Worker shutdown complete")

    async def _run_job(self, job, blob_client: BlobStorageClient) -> None:
        async with get_session() as session:
            await process_job(job, self._config, session, blob_client)

    async def _recover_stale(self) -> None:
        """Mark any documents stuck in 'compiling' state as failed on startup."""
        async with get_session() as session:
            result = await session.execute(
                update(documents)
                .where(
                    documents.c.status == "compiling",
                    documents.c.deleted_at.is_(None),
                )
                .values(
                    status="failed",
                    failure_reason="Worker restarted with job in progress — marked failed for safety",
                    updated_at=text("NOW()"),
                )
                .returning(documents.c.id)
            )
            stale_ids = result.fetchall()
            count = len(stale_ids)
            if count:
                logger.info("Stale recovery: %d stale documents resolved", count)
            else:
                logger.debug("Stale recovery: no stale documents found")

    def _handle_signal(self, signum: int, frame) -> None:
        logger.info("Received signal %d — shutting down after current job", signum)
        self._shutdown = True
