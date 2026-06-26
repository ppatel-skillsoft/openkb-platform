from __future__ import annotations

import logging
from dataclasses import dataclass

from fastmcp import Context
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from mcp_server.db import get_session
from mcp_server.exceptions import GeneratorAPIError

logger = logging.getLogger(__name__)


@dataclass
class KBSummary:
    id: str
    name: str
    document_count: int
    ready: bool


async def list_kbs(ctx: Context) -> list[KBSummary]:
    """List all knowledge bases that have at least one compiled document.

    Returns each KB's ``id``, ``name``, ``document_count``, and
    ``ready`` status.  Call this tool first to discover valid ``kb_id``
    values for ``ask_kb``.
    """
    logger.info("list_kbs called")

    query = text(
        """
        SELECT
            kb.id::text      AS id,
            kb.name          AS name,
            COUNT(d.id)      AS document_count
        FROM knowledge_bases kb
        JOIN documents d
          ON d.kb_id = kb.id
         AND d.status = 'complete'
         AND d.deleted_at IS NULL
        WHERE kb.deleted_at IS NULL
        GROUP BY kb.id, kb.name
        HAVING COUNT(d.id) > 0
        ORDER BY kb.name
        """
    )

    try:
        async with get_session() as session:
            result = await session.execute(query)
            rows = result.fetchall()
    except SQLAlchemyError as exc:
        logger.error("list_kbs DB query failed: %s", exc)
        raise GeneratorAPIError(f"Database error while listing KBs: {exc}") from exc

    return [
        KBSummary(
            id=row.id,
            name=row.name,
            document_count=int(row.document_count),
            ready=True,
        )
        for row in rows
    ]
