from __future__ import annotations

"""openkb.db — Phase 0 database connectivity and schema definitions.

Public API (per contracts/db-session-factory.md):

    Engine / session factory
    -------------------------
    get_engine()       → AsyncEngine
    get_session()      → AsyncContextManager[AsyncSession]
    get_connection()   → AsyncContextManager[AsyncConnection]
    ConfigurationError

    Schema objects (SQLAlchemy Table references)
    ---------------------------------------------
    metadata           → MetaData  (registered with all three tables)
    knowledge_bases    → Table
    documents          → Table
    wiki_pages         → Table

Example::

    from openkb.db import get_session, knowledge_bases
    from sqlalchemy import select

    async with get_session() as session:
        rows = (await session.execute(select(knowledge_bases))).fetchall()
"""

from openkb.db.engine import (
    ConfigurationError,
    get_connection,
    get_engine,
    get_session,
)
from openkb.db.metadata import (
    documents,
    knowledge_bases,
    metadata,
    wiki_pages,
)

__all__ = [
    # Engine / session factory
    "get_engine",
    "get_session",
    "get_connection",
    "ConfigurationError",
    # Schema objects
    "metadata",
    "knowledge_bases",
    "documents",
    "wiki_pages",
]
