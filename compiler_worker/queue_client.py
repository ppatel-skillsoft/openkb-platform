from __future__ import annotations

import json
import logging
from typing import Protocol

import redis as redis_lib

from compiler_worker.models import CompilationJob

logger = logging.getLogger(__name__)


class QueueClient(Protocol):
    """Abstract queue consumer interface."""

    def dequeue(self, timeout: int) -> str | None:
        """Block up to *timeout* seconds; return raw JSON string or ``None``."""
        ...


class RedisQueueClient:
    """Concrete BRPOP-based queue consumer backed by Redis."""

    def __init__(self, redis_url: str, queue_key: str) -> None:
        # socket_timeout=None: let BRPOP manage its own server-side timeout;
        # a finite socket timeout would race with the BRPOP block duration.
        self._client = redis_lib.from_url(
            redis_url, decode_responses=True, socket_timeout=None, socket_connect_timeout=5
        )
        self._queue_key = queue_key

    def dequeue(self, timeout: int) -> str | None:
        """Block up to *timeout* seconds; return raw JSON string or ``None``."""
        result = self._client.brpop(self._queue_key, timeout=timeout)
        if result is None:
            return None
        _, raw = result
        return raw


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
