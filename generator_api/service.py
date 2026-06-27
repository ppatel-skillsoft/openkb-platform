"""Business logic for document lifecycle operations in the generator API."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from generator_api.blob import (
    BlobSyncError,
    delete_summary_blob,
    rebuild_index_md,
    sync_wiki_tree,
    upload_index_to_blob,
)
from generator_api.exceptions import DocumentNotFoundError, KBNotFoundError

logger = logging.getLogger(__name__)

_EMPTY_INDEX = """# Knowledge Base Index

## Documents

## Concepts

## Entities

## Explorations
"""


async def service_delete_document(
    kb_id: str,
    doc_id: str,
    db: AsyncSession,
    connection_string: str,
) -> None:
    """Soft-delete a document and rebuild the KB index without any LLM calls.

    Steps:
    1. Resolve the KB row — raises :exc:`~generator_api.exceptions.KBNotFoundError`
       if the KB does not exist or is deleted.
    2. Resolve the document row — raises
       :exc:`~generator_api.exceptions.DocumentNotFoundError` if the document
       does not exist or belongs to a different KB.
    3. Return immediately if the document is already deleted (idempotency).
    4. Set ``documents.deleted_at`` to the current UTC timestamp.
    5. Delete ``wiki/summaries/{doc_slug}.md`` from blob storage.
    6. Download remaining wiki blobs, rebuild ``index.md``, upload it.

    Args:
        kb_id: UUID string for the knowledge base.
        doc_id: UUID string for the document to remove.
        db: Async SQLAlchemy session (injected by FastAPI).
        connection_string: Azure Blob Storage connection string.
    """
    # ── 1. Resolve KB ────────────────────────────────────────────────────────
    kb_row = (
        await db.execute(
            text(
                "SELECT id, slug, storage_container_path "
                "FROM knowledge_bases "
                "WHERE id = :kb_id AND deleted_at IS NULL"
            ),
            {"kb_id": kb_id},
        )
    ).one_or_none()
    if kb_row is None:
        raise KBNotFoundError(kb_id)

    container: str = kb_row.storage_container_path or f"kb-{kb_id}"

    # ── 2. Resolve document ───────────────────────────────────────────────────
    doc_row = (
        await db.execute(
            text(
                "SELECT id, slug, deleted_at "
                "FROM documents "
                "WHERE id = :doc_id AND kb_id = :kb_id"
            ),
            {"doc_id": doc_id, "kb_id": kb_id},
        )
    ).one_or_none()
    if doc_row is None:
        raise DocumentNotFoundError(doc_id, kb_id)

    # ── 3. Idempotency guard ──────────────────────────────────────────────────
    if doc_row.deleted_at is not None:
        logger.info(
            "Document already deleted — returning early doc_id=%s kb_id=%s",
            doc_id,
            kb_id,
        )
        return

    doc_slug: str = doc_row.slug

    # ── 4. Soft-delete ────────────────────────────────────────────────────────
    await db.execute(
        text(
            "UPDATE documents "
            "SET deleted_at = timezone('utc', NOW()) "
            "WHERE id = :doc_id"
        ),
        {"doc_id": doc_id},
    )
    await db.commit()
    logger.info(
        "Soft-deleted document kb_id=%s doc_id=%s slug=%s", kb_id, doc_id, doc_slug
    )

    # ── 5. Remove summary blob ────────────────────────────────────────────────
    await delete_summary_blob(connection_string, container, doc_slug)

    # ── 6. Rebuild index ──────────────────────────────────────────────────────
    scratch_dir = Path(tempfile.mkdtemp(prefix="openkb-delete-"))
    try:
        wiki_dir = scratch_dir / "wiki"
        try:
            await sync_wiki_tree(connection_string, container, "wiki/", scratch_dir)
        except BlobSyncError as exc:
            if "no blobs found" in str(exc).lower():
                logger.warning(
                    "No wiki blobs remain for kb_id=%s — writing empty index", kb_id
                )
                wiki_dir.mkdir(parents=True, exist_ok=True)
                (wiki_dir / "index.md").write_text(_EMPTY_INDEX, encoding="utf-8")
            else:
                logger.error(
                    "BlobSyncError during index rebuild for kb_id=%s: %s", kb_id, exc
                )
                raise
        else:
            rebuild_index_md(wiki_dir)

        await upload_index_to_blob(connection_string, container, wiki_dir / "index.md")
        logger.info("Index rebuilt and uploaded for kb_id=%s", kb_id)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
