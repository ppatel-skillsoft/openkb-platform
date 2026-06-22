from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError as AzureNotFoundError
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from compiler_worker.blob_client import BlobStorageClient
from compiler_worker.config import WorkerConfig
from compiler_worker.exceptions import (
    BlobNotFoundError,
    KBNotFoundError,
    SidecarCompileError,
    SidecarTimeoutError,
)
from compiler_worker.models import CompilationJob
from compiler_worker.sidecar import SidecarProcess
from openkb.db import documents, knowledge_bases, wiki_pages

logger = logging.getLogger(__name__)


async def process_job(
    job: CompilationJob,
    config: WorkerConfig,
    db_session: AsyncSession,
    blob_client: BlobStorageClient,
) -> None:
    """Orchestrate a single compilation job end-to-end.

    Steps:
        1. Look up the ``knowledge_bases`` row; raise ``KBNotFoundError`` if absent.
        2. Create a scratch directory and download the source blob.
        3. Transition ``documents.status`` to ``'compiling'``.
        4. Spawn sidecar, drive ``init → add → status`` polling.
        5. Upload each wiki-page blob; upsert ``wiki_pages`` rows.
        6. Mark ``documents.status = 'complete'``.
        7. On any failure: mark ``documents.status = 'failed'`` with reason.
        8. Always: teardown sidecar and remove scratch directory.
    """
    logger.info("Processing job %s for document %s", job.job_id, job.document_id)

    # ------------------------------------------------------------------
    # 1. Look up knowledge_bases row
    # ------------------------------------------------------------------
    kb_result = await db_session.execute(
        select(
            knowledge_bases.c.id,
            knowledge_bases.c.storage_container_path,
            knowledge_bases.c.compilation_config,
            knowledge_bases.c.status,
        ).where(
            knowledge_bases.c.id == job.kb_id,
            knowledge_bases.c.deleted_at.is_(None),
        )
    )
    kb_row = kb_result.fetchone()
    if kb_row is None:
        raise KBNotFoundError(f"knowledge_bases row not found for kb_id: {job.kb_id}")

    compilation_config = kb_row.compilation_config or {}
    model = compilation_config.get("model", "gpt-4o-mini")
    language = compilation_config.get("language", "en")
    container = kb_row.storage_container_path or f"kb-{job.kb_id}"

    # ------------------------------------------------------------------
    # 2. Create scratch directory and download source blob
    # ------------------------------------------------------------------
    # If COMPILER_WORKER_SCRATCH_ROOT is set, create the scratch dir there so
    # that a shared Docker volume makes it visible to the isolation-tests
    # container (spec 006 FR-007). Otherwise use the system temp dir.
    scratch_dir = Path(
        tempfile.mkdtemp(
            prefix="openkb-job-",
            dir=config.scratch_dir_root,
        )
    )
    raw_dir = scratch_dir / "raw"
    raw_dir.mkdir()
    dest_file = raw_dir / job.filename

    try:
        blob_client.download_to_file(job.blob_path, dest_file)
    except AzureNotFoundError as exc:
        logger.error("Source blob not found for job %s: %s", job.job_id, job.blob_path)
        await _mark_failed(db_session, job.document_id, "Source blob not found in storage")
        shutil.rmtree(scratch_dir, ignore_errors=True)
        return

    # ------------------------------------------------------------------
    # 3. Transition document to 'compiling'
    # ------------------------------------------------------------------
    await db_session.execute(
        update(documents)
        .where(documents.c.id == job.document_id)
        .values(status="compiling", updated_at=text("NOW()"))
    )
    await db_session.flush()

    # ------------------------------------------------------------------
    # 4–6. Sidecar + upload + DB update (always teardown + cleanup)
    # ------------------------------------------------------------------
    sidecar = SidecarProcess()
    try:
        sidecar.start(config, scratch_dir)
        sidecar.init(model, language)
        sidecar.add(job.filename)

        # Poll /status until complete or timeout
        deadline = time.monotonic() + config.sidecar_compile_timeout
        final_status = None
        while time.monotonic() < deadline:
            status = sidecar.get_status()  # raises SidecarCompileError on 'failed'
            if status.status == "complete":
                final_status = status
                break
            time.sleep(config.sidecar_poll_interval)

        if final_status is None:
            raise SidecarTimeoutError(config.sidecar_compile_timeout)

        # Upload wiki pages to Blob Storage
        blob_client.ensure_container(container)
        for page in final_status.pages:
            page_file = scratch_dir / page.file_path
            wiki_blob_name = f"wiki/{page.slug}.md"
            wiki_blob_path = f"{container}/{wiki_blob_name}"
            blob_client.upload_from_file(wiki_blob_path, page_file)

            # Upsert wiki_pages row
            await db_session.execute(
                pg_insert(wiki_pages).values(
                    kb_id=job.kb_id,
                    page_type=page.page_type,
                    slug=page.slug,
                    blob_path=wiki_blob_path,
                    entity_type=page.entity_type,
                    last_compiled_at=text("NOW()"),
                    created_at=text("NOW()"),
                    updated_at=text("NOW()"),
                ).on_conflict_do_update(
                    constraint="uq_wiki_pages_kb_id_slug",
                    set_={
                        "page_type": page.page_type,
                        "blob_path": wiki_blob_path,
                        "entity_type": page.entity_type,
                        "last_compiled_at": text("NOW()"),
                        "updated_at": text("NOW()"),
                    },
                )
            )

        # Mark document complete
        await db_session.execute(
            update(documents)
            .where(documents.c.id == job.document_id)
            .values(
                status="complete",
                token_cost=final_status.token_cost,
                pageindex_used=final_status.pageindex_used,
                updated_at=text("NOW()"),
            )
        )
        logger.info(
            "Job %s completed: %d pages, token_cost=%s",
            job.job_id,
            len(final_status.pages),
            final_status.token_cost,
        )

    except KBNotFoundError as exc:
        await _mark_failed(db_session, job.document_id, str(exc))
    except BlobNotFoundError as exc:
        await _mark_failed(db_session, job.document_id, "Source blob not found in storage")
    except SidecarCompileError as exc:
        await _mark_failed(db_session, job.document_id, exc.reason)
    except SidecarTimeoutError as exc:
        await _mark_failed(
            db_session,
            job.document_id,
            f"Compilation timed out after {exc.timeout_s}s",
        )
    except Exception as exc:
        logger.exception("Unexpected error processing job %s", job.job_id)
        # R-008: if blob upload succeeded before this Postgres failure, the wiki
        # blobs are already in storage but the DB record will show 'failed'.
        await _mark_failed(db_session, job.document_id, repr(exc))
    finally:
        sidecar.teardown()
        shutil.rmtree(scratch_dir, ignore_errors=True)


async def _mark_failed(
    db_session: AsyncSession,
    document_id: str,
    reason: str,
) -> None:
    logger.error("Marking document %s failed: %s", document_id, reason)
    await db_session.execute(
        update(documents)
        .where(documents.c.id == document_id)
        .values(status="failed", failure_reason=reason, updated_at=text("NOW()"))
    )
