from __future__ import annotations

import asyncio
import logging
import signal

from compiler_worker.blob_client import BlobStorageClient
from compiler_worker.config import WorkerConfig
from compiler_worker.job import process_job
from compiler_worker.queue_client import RedisQueueClient, parse_job
from openkb.db import documents, get_session
from sqlalchemy import text, update

logger = logging.getLogger(__name__)


class WorkerLoop:
    """Main worker loop: dequeues jobs from Redis and processes them one at a time."""

    def __init__(self, config: WorkerConfig) -> None:
        self._config = config
        self._shutdown = False

    def run(self) -> None:
        """Configure logging then hand off to the single async run."""
        logging.basicConfig(
            level=self._config.log_level,
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        )
        # Register OS-level signal handlers before entering the event loop.
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        asyncio.run(self._async_run())

    async def _async_run(self) -> None:
        """Single async entry point — stale recovery then the BRPOP poll loop.

        The blocking ``dequeue()`` call is offloaded to a thread executor so it
        never blocks the event loop, and the asyncpg connection pool stays bound
        to this single event loop for its entire lifetime.
        """
        logger.info("Worker started — polling %s", self._config.queue_key)

        await self._recover_stale()

        queue = RedisQueueClient(self._config.redis_url, self._config.queue_key)
        blob_client = BlobStorageClient(self._config.blob_connection_string)
        loop = asyncio.get_running_loop()

        while not self._shutdown:
            # Run blocking BRPOP in a thread so the event loop stays free.
            raw = await loop.run_in_executor(
                None, queue.dequeue, self._config.queue_poll_timeout
            )
            if raw is None:
                logger.debug("No job in queue; polling again")
                continue

            job = parse_job(raw)
            if job is None:
                continue

            logger.info("Dequeued job %s for document %s", job.job_id, job.document_id)
            try:
                async with get_session() as session:
                    await process_job(job, self._config, session, blob_client)
            except Exception:
                logger.exception("Unhandled error processing job %s — worker continues", job.job_id)

        logger.info("Worker shutdown complete")

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
