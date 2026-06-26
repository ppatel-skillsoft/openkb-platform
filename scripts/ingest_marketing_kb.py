"""Ingest Skillsoft marketing documents into the OpenKB pipeline.

Reads all .docx and .pptx files from marketing_kb/ (or MARKETING_KB_DIR),
creates a knowledge base row, uploads each file to Azurite, and enqueues
a compiler_job for each document.

Idempotent: already-ingested documents (matched by original_filename) are
skipped on re-runs. The KB row is created with ON CONFLICT DO NOTHING.

Concurrency: asyncio.Semaphore(3) bounds parallel blob uploads so Azurite
and the local network are not overwhelmed.

Rate-limiting (OpenAI 429): The compiler-worker processes one job at a time.
This script staggers job enqueues with a short delay (JOB_ENQUEUE_DELAY_S)
to give the worker breathing room and avoid bursting all jobs simultaneously.

Blob uploads: tenacity retries transient Azure SDK errors (ServiceRequestError,
HttpResponseError with 5xx status) up to 5 times with exponential back-off.

Usage:
    uv run python scripts/ingest_marketing_kb.py [--dry-run] [--kb-dir PATH]

Environment variables (or .env file):
    DATABASE_URL                     — async SQLAlchemy URL (asyncpg)
    AZURE_STORAGE_CONNECTION_STRING  — Azurite / Azure Blob connection string
    MARKETING_KB_DIR                 — override default marketing_kb/ location
    JOB_ENQUEUE_DELAY_S              — seconds to wait between job inserts (default 1.0)
    UPLOAD_CONCURRENCY               — max parallel blob uploads (default 3)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Allow running from repo root without installing as a package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from azure.core.exceptions import HttpResponseError, ServiceRequestError  # noqa: E402
from azure.storage.blob.aio import BlobServiceClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from tenacity import (  # noqa: E402
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from openkb.db.metadata import compiler_jobs, documents, knowledge_bases  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUPPORTED_EXTENSIONS = {".docx", ".pptx"}
_SKIP_NAMES = {".DS_Store", ".agent"}

MARKETING_KB_SLUG = "marketing-kb"
MARKETING_KB_NAME = "Skillsoft Marketing Knowledge Base"

_DEFAULT_KB_DIR = Path(__file__).parent.parent / "marketing_kb"
_DEFAULT_CONNECTION_STRING = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://localhost:10000/devstoreaccount1;"
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class IngestConfig:
    database_url: str
    connection_string: str
    kb_dir: Path
    dry_run: bool = False
    upload_concurrency: int = 3
    job_enqueue_delay_s: float = 1.0


def _load_config(args: argparse.Namespace) -> IngestConfig:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        logger.error("DATABASE_URL is not set. Copy .env.example to .env.")
        sys.exit(1)

    connection_string = os.environ.get(
        "AZURE_STORAGE_CONNECTION_STRING", _DEFAULT_CONNECTION_STRING
    )

    kb_dir_env = os.environ.get("MARKETING_KB_DIR", "")
    kb_dir = (
        Path(args.kb_dir)
        if args.kb_dir
        else (Path(kb_dir_env) if kb_dir_env else _DEFAULT_KB_DIR)
    )

    return IngestConfig(
        database_url=database_url,
        connection_string=connection_string,
        kb_dir=kb_dir,
        dry_run=args.dry_run,
        upload_concurrency=int(os.environ.get("UPLOAD_CONCURRENCY", "3")),
        job_enqueue_delay_s=float(os.environ.get("JOB_ENQUEUE_DELAY_S", "1.0")),
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def discover_files(kb_dir: Path) -> list[Path]:
    """Return all ingestible files under kb_dir, sorted deterministically."""
    files = []
    for path in sorted(kb_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
            continue
        if path.name in _SKIP_NAMES or path.name.startswith("."):
            continue
        files.append(path)
    return files


# ---------------------------------------------------------------------------
# Azure Blob upload (with tenacity retry)
# ---------------------------------------------------------------------------


@retry(
    retry=retry_if_exception_type((ServiceRequestError, HttpResponseError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _upload_blob(
    blob_client,  # azure.storage.blob.aio.BlobClient
    file_path: Path,
) -> None:
    """Upload a single file to Azurite/Azure Blob with automatic retry."""
    with file_path.open("rb") as data:
        await blob_client.upload_blob(data, overwrite=True)


# ---------------------------------------------------------------------------
# Ingest one document
# ---------------------------------------------------------------------------


@dataclass
class IngestResult:
    filename: str
    skipped: bool = False
    success: bool = False
    error: str | None = None


async def _ingest_one(
    *,
    file_path: Path,
    kb_id: str,
    container_name: str,
    blob_service: BlobServiceClient,
    session: AsyncSession,
    semaphore: asyncio.Semaphore,
) -> IngestResult:
    filename = file_path.name
    blob_path = f"{container_name}/raw/{filename}"

    # Check idempotency — skip if already ingested.
    existing = (
        await session.execute(
            select(documents.c.id).where(
                documents.c.kb_id == kb_id,
                documents.c.original_filename == filename,
            )
        )
    ).fetchone()

    if existing:
        logger.info("  SKIP  %s (already ingested)", filename)
        return IngestResult(filename=filename, skipped=True)

    try:
        # 1. Insert document row (status=pending).
        doc_result = await session.execute(
            documents.insert()
            .values(
                kb_id=kb_id,
                source_type="upload",
                original_filename=filename,
                status="pending",
            )
            .returning(documents.c.id)
        )
        doc_id = doc_result.scalar_one()

        # 2. Upload blob to Azurite (with semaphore for concurrency control).
        async with semaphore:
            blob_client = blob_service.get_blob_client(
                container=container_name, blob=f"raw/{filename}"
            )
            await _upload_blob(blob_client, file_path)

        # 3. Enqueue compiler_job.
        await session.execute(
            compiler_jobs.insert().values(
                kb_id=kb_id,
                document_id=doc_id,
                blob_path=blob_path,
                filename=filename,
            )
        )

        logger.info("  OK    %s → job enqueued (doc_id=%s)", filename, doc_id)
        return IngestResult(filename=filename, success=True)

    except Exception as exc:
        logger.error("  FAIL  %s — %s: %s", filename, type(exc).__name__, exc)
        return IngestResult(filename=filename, error=str(exc))


# ---------------------------------------------------------------------------
# Main ingestion flow
# ---------------------------------------------------------------------------


@dataclass
class IngestionReport:
    total: int = 0
    skipped: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


async def ingest(cfg: IngestConfig) -> IngestionReport:
    """Run the full ingestion pipeline."""
    report = IngestionReport()

    # ── Validate KB directory ────────────────────────────────────────────────
    if not cfg.kb_dir.is_dir():
        logger.error("KB directory not found: %s", cfg.kb_dir)
        sys.exit(1)

    files = discover_files(cfg.kb_dir)
    if not files:
        logger.warning(
            "No .docx/.pptx files found in %s — nothing to ingest.", cfg.kb_dir
        )
        return report

    report.total = len(files)
    logger.info("Found %d ingestible file(s) in %s", len(files), cfg.kb_dir)
    for f in files:
        logger.info("  • %s", f.relative_to(cfg.kb_dir))

    if cfg.dry_run:
        logger.info("\n[DRY-RUN] No database writes or blob uploads will be performed.")
        logger.info(
            "[DRY-RUN] %d file(s) would be ingested into KB '%s'.\n",
            len(files),
            MARKETING_KB_SLUG,
        )
        for file_path in files:
            logger.info("  DRY   %s", file_path.name)
        report.succeeded = len(files)
        return report

    # ── Database setup ───────────────────────────────────────────────────────
    from openkb.db.engine import _extract_ssl_connect_args

    db_url, connect_args = _extract_ssl_connect_args(cfg.database_url)
    engine = create_async_engine(db_url, echo=False, connect_args=connect_args)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # ── Ensure KB row exists ─────────────────────────────────────────────
        stmt = (
            pg_insert(knowledge_bases)
            .values(
                name=MARKETING_KB_NAME,
                slug=MARKETING_KB_SLUG,
                status="active",
                compilation_config={
                    "language": "en",
                    "pageindex_threshold": 0.5,
                    "entity_types": ["organization", "product", "concept"],
                    "extra_headers": {},
                },
            )
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        await session.execute(stmt)
        await session.flush()

        kb_row = (
            await session.execute(
                select(knowledge_bases.c.id).where(
                    knowledge_bases.c.slug == MARKETING_KB_SLUG
                )
            )
        ).fetchone()

        if kb_row is None:
            logger.error(
                "Failed to find/create KB '%s'. Is the DB reachable?", MARKETING_KB_SLUG
            )
            sys.exit(1)

        kb_id = str(kb_row[0])
        logger.info("Knowledge base: %s (id=%s)", MARKETING_KB_SLUG, kb_id)

        container_name = f"kb-{kb_id}"

        # ── Ensure blob container exists ─────────────────────────────────────
        async with BlobServiceClient.from_connection_string(
            cfg.connection_string
        ) as blob_service:
            container_client = blob_service.get_container_client(container_name)
            try:
                await container_client.create_container()
                logger.info("Blob container created: %s", container_name)
            except Exception:
                logger.info("Blob container already exists: %s", container_name)

        # ── Ingest files ─────────────────────────────────────────────────────
        semaphore = asyncio.Semaphore(cfg.upload_concurrency)

        async with BlobServiceClient.from_connection_string(
            cfg.connection_string
        ) as blob_service:
            for file_path in files:
                result = await _ingest_one(
                    file_path=file_path,
                    kb_id=kb_id,
                    container_name=container_name,
                    blob_service=blob_service,
                    session=session,
                    semaphore=semaphore,
                )

                if result.skipped:
                    report.skipped += 1
                elif result.success:
                    report.succeeded += 1
                    # Stagger job enqueues to give the compiler-worker breathing
                    # room so OpenAI requests are spread over time (avoids 429).
                    if cfg.job_enqueue_delay_s > 0:
                        await asyncio.sleep(cfg.job_enqueue_delay_s)
                else:
                    report.failed += 1
                    if result.error:
                        report.errors.append((result.filename, result.error))

            await session.commit()
            logger.info("Transaction committed.")

    await engine.dispose()
    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest Skillsoft marketing documents into OpenKB pipeline.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be ingested without writing to DB or uploading blobs.",
    )
    parser.add_argument(
        "--kb-dir",
        metavar="PATH",
        default=None,
        help=f"Override marketing KB directory (default: {_DEFAULT_KB_DIR})",
    )
    return parser.parse_args()


async def _main() -> None:
    args = _parse_args()
    cfg = _load_config(args)

    logger.info("=" * 60)
    logger.info("OpenKB Marketing Ingestion Script")
    logger.info("  KB dir  : %s", cfg.kb_dir)
    logger.info("  Dry run : %s", cfg.dry_run)
    logger.info("  Concurr : %d upload slots", cfg.upload_concurrency)
    logger.info("  Delay   : %.1fs between job enqueues", cfg.job_enqueue_delay_s)
    logger.info("=" * 60)

    report = await ingest(cfg)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Ingestion complete")
    logger.info("  Total    : %d", report.total)
    logger.info("  Succeeded: %d", report.succeeded)
    logger.info("  Skipped  : %d", report.skipped)
    logger.info("  Failed   : %d", report.failed)
    if report.errors:
        logger.info("  Errors:")
        for filename, error in report.errors:
            logger.info("    - %s: %s", filename, error)
    logger.info("=" * 60)

    if report.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
