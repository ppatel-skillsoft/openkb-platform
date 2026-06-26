from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from fastmcp import Context

from mcp_server.exceptions import GeneratorAPIError, KBNotFoundError, KBNotReadyError

logger = logging.getLogger(__name__)


@dataclass
class KBAnswer:
    answer: str
    citations: list[Any]
    tokens_used: int
    kb_id: str


def _validate_kb_id(kb_id: str) -> None:
    """Raise ``ValueError`` if ``kb_id`` is not a valid UUID v4."""
    try:
        parsed = uuid.UUID(kb_id, version=4)
        if str(parsed) != kb_id.lower():
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"kb_id must be a valid UUID v4, got: {kb_id!r}") from exc


def _validate_question(question: str) -> str:
    """Strip and validate the question. Raises ``ValueError`` on invalid input."""
    stripped = question.strip()
    if not stripped:
        raise ValueError("question must not be blank")
    if len(stripped) > 8000:
        raise ValueError("question must be 8000 characters or fewer")
    return stripped


async def ask_kb(kb_id: str, question: str, ctx: Context) -> KBAnswer:
    """Query a compiled knowledge base with a natural-language question.

    Use ``list_kbs`` to discover available ``kb_id`` values before calling
    this tool.  The answer is grounded in the KB content and includes
    source citations.

    Args:
        kb_id: UUID of the knowledge base to query.
        question: Natural-language question (1–8000 characters).
    """
    _validate_kb_id(kb_id)
    question = _validate_question(question)

    client: httpx.AsyncClient = ctx.lifespan_context["http_client"]

    logger.info("ask_kb kb_id=%s question_length=%d", kb_id, len(question))

    try:
        resp = await client.post(
            f"/kbs/{kb_id}/query",
            json={"question": question},
        )
    except httpx.TimeoutException as exc:
        logger.warning("ask_kb timed out for kb_id=%s: %s", kb_id, exc)
        raise GeneratorAPIError(
            "Request to generator-api timed out", status_code=504
        ) from exc
    except httpx.RequestError as exc:
        logger.warning("ask_kb connection error for kb_id=%s: %s", kb_id, exc)
        raise GeneratorAPIError(
            f"Could not reach generator-api: {exc}", status_code=503
        ) from exc

    if resp.status_code == 404:
        raise KBNotFoundError(kb_id)
    if resp.status_code == 409:
        raise KBNotReadyError(kb_id)
    if resp.status_code >= 500:
        raise GeneratorAPIError(
            f"generator-api returned {resp.status_code}",
            status_code=resp.status_code,
        )
    if not resp.is_success:
        raise GeneratorAPIError(
            f"Unexpected status {resp.status_code} from generator-api",
            status_code=resp.status_code,
        )

    data = resp.json()
    return KBAnswer(
        answer=data.get("answer", ""),
        citations=data.get("citations", []),
        tokens_used=data.get("tokens_used", 0),
        kb_id=kb_id,
    )
