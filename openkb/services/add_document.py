from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from openkb.config import DEFAULT_CONFIG
from openkb.converter import _registry_path, convert_document
from openkb.services import (
    KBAddResult,
    KBNotFoundError,
    LLMError,
    UnsupportedDocumentError,
    URLFetchError,
)
from openkb.storage.base import StorageBackend
from openkb.storage.local import LocalStorageBackend

logger = logging.getLogger(__name__)

# Mirror of SUPPORTED_EXTENSIONS in openkb/cli.py
SUPPORTED_EXTENSIONS = {
    ".pdf", ".md", ".markdown", ".docx", ".pptx", ".xlsx", ".xls",
    ".html", ".htm", ".txt", ".csv",
}

_CONTENT_TYPE_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/markdown": ".md",
    "text/plain": ".txt",
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "text/csv": ".csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

_MAX_STEM = 80


def _safe_stem(s: str) -> str:
    decoded = unquote(s)
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", decoded)
    stem = re.sub(r"-+", "-", stem).strip("-._")
    return stem[:_MAX_STEM].rstrip("-._") or "document"


def _ext_from_url(url: str, content_type: str) -> str:
    """Determine file extension from URL path, falling back to Content-Type."""
    path = urlparse(url).path
    suffix = Path(unquote(path)).suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return suffix
    main_type = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(main_type, "")


async def _fetch_url(url: str) -> tuple[bytes, str]:
    """Fetch URL bytes via httpx. Returns (bytes, content_type)."""
    try:
        import httpx
    except ImportError:
        raise URLFetchError(url, "httpx not installed; install openkb[api]")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url, headers={"User-Agent": "openkb/api"})
        if response.status_code != 200:
            raise URLFetchError(url, f"HTTP {response.status_code}")
        return response.content, response.headers.get("content-type", "")
    except URLFetchError:
        raise
    except Exception as exc:
        raise URLFetchError(url, str(exc)) from exc


async def _run_pipeline(file_path: Path, kb_dir: Path, model: str) -> tuple[str, bool, dict]:
    """Convert + compile a document. Returns (doc_name, skipped, meta).

    Uses asyncio.to_thread for synchronous convert_document to keep the
    event loop unblocked, then awaits the async compile coroutines directly.
    """
    from openkb.agent.compiler import compile_long_doc, compile_short_doc
    from openkb.state import HashRegistry

    # convert_document is CPU/IO-bound sync — run in a thread
    result = await asyncio.to_thread(convert_document, file_path, kb_dir)

    if result.skipped:
        return result.doc_name or file_path.stem, True, {}

    doc_name = result.doc_name or file_path.stem
    index_result = None

    try:
        if result.is_long_doc:
            from openkb.indexer import index_long_document
            index_result = await asyncio.to_thread(
                index_long_document, result.raw_path, kb_dir, doc_name
            )
            summary_path = kb_dir / "wiki" / "summaries" / f"{doc_name}.md"
            for attempt in range(2):
                try:
                    await compile_long_doc(
                        doc_name, summary_path, index_result.doc_id, kb_dir, model,
                        doc_description=index_result.description,
                    )
                    break
                except Exception:
                    if attempt == 1:
                        raise
        else:
            for attempt in range(2):
                try:
                    await compile_short_doc(doc_name, result.source_path, kb_dir, model)
                    break
                except Exception:
                    if attempt == 1:
                        raise
    except Exception as exc:
        try:
            import litellm
            if isinstance(exc, (
                litellm.exceptions.APIError,
                litellm.exceptions.AuthenticationError,
                litellm.exceptions.RateLimitError,
                litellm.exceptions.Timeout,
            )):
                raise LLMError(str(exc)) from exc
        except ImportError:
            pass
        raise

    doc_type = "long_pdf" if result.is_long_doc else file_path.suffix.lstrip(".")
    meta: dict = {
        "name": file_path.name,
        "doc_name": doc_name,
        "type": doc_type,
        "path": _registry_path(file_path, kb_dir),
    }
    if result.raw_path is not None:
        meta["raw_path"] = _registry_path(result.raw_path, kb_dir)
    if result.source_path is not None:
        meta["source_path"] = _registry_path(result.source_path, kb_dir)
    if index_result is not None:
        meta["doc_id"] = index_result.doc_id

    return doc_name, False, meta


def _register_hash(kb_dir: Path, file_hash: str, doc_name: str, meta: dict) -> None:
    """Atomically update hashes.json with the new document entry."""
    from openkb.locks import atomic_write_json
    from openkb.state import HashRegistry
    registry = HashRegistry(kb_dir / ".openkb" / "hashes.json")
    registry.remove_by_doc_name(doc_name)
    registry.add(file_hash, meta)
    atomic_write_json(kb_dir / ".openkb" / "hashes.json", registry.all_entries())


async def service_add_document(
    backend: StorageBackend,
    kb_name: str,
    source: str,
) -> KBAddResult:
    """Add a document (local path or URL) to an existing KB.

    Returns KBAddResult with status "added" or "skipped".
    Raises:
        KBNotFoundError: KB does not exist.
        UnsupportedDocumentError: file extension not supported.
        URLFetchError: URL fetch failed.
        LLMError: LiteLLM compilation error.
        LockTimeoutError: could not acquire ingest lock.
    """
    # 1. Verify KB exists
    if not await backend.exists(".openkb/config.yaml"):
        raise KBNotFoundError(kb_name)

    # 2. Acquire raw bytes and determine filename
    is_url = source.startswith(("http://", "https://"))
    if is_url:
        raw_bytes, content_type = await _fetch_url(source)
        url_path = urlparse(source).path
        stem = _safe_stem(Path(unquote(url_path)).stem or "document")
        ext = _ext_from_url(source, content_type)
        if not ext or ext not in SUPPORTED_EXTENSIONS:
            raise UnsupportedDocumentError(ext or "(unknown)", SUPPORTED_EXTENSIONS)
        filename = f"{stem}{ext}"
    else:
        src_path = Path(source)
        ext = src_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise UnsupportedDocumentError(ext, SUPPORTED_EXTENSIONS)
        raw_bytes = await asyncio.to_thread(src_path.read_bytes)
        filename = src_path.name

    # 3. Early hash check before acquiring the lock
    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    try:
        hashes_bytes = await backend.read_bytes(".openkb/hashes.json")
        registry_data: dict = json.loads(hashes_bytes)
    except Exception:
        registry_data = {}

    if file_hash in registry_data:
        stored = registry_data[file_hash]
        doc_name = stored.get("doc_name") or Path(stored.get("name", filename)).stem
        return KBAddResult(
            status="skipped",
            doc_name=doc_name,
            message=f"Already in knowledge base: {filename}",
        )

    # 4. Acquire distributed lock and run the full ingest pipeline
    async with backend.lock():
        # Re-check under lock (another worker may have added between check and lock)
        try:
            hashes_bytes = await backend.read_bytes(".openkb/hashes.json")
            registry_data = json.loads(hashes_bytes)
        except Exception:
            registry_data = {}
        if file_hash in registry_data:
            stored = registry_data[file_hash]
            doc_name = stored.get("doc_name") or Path(stored.get("name", filename)).stem
            return KBAddResult(
                status="skipped",
                doc_name=doc_name,
                message=f"Already in knowledge base: {filename}",
            )

        # Load model name from KB config
        try:
            config_bytes = await backend.read_bytes(".openkb/config.yaml")
            config = yaml.safe_load(config_bytes.decode()) or {}
        except Exception:
            config = {}
        model: str = config.get("model", DEFAULT_CONFIG["model"])

        # Write raw bytes to raw/ via backend
        await backend.write_bytes(f"raw/{filename}", raw_bytes)

        if isinstance(backend, LocalStorageBackend):
            kb_dir = backend.kb_dir
            raw_file = kb_dir / "raw" / filename
            doc_name, skipped, meta = await _run_pipeline(raw_file, kb_dir, model)
            if not skipped:
                await asyncio.to_thread(_register_hash, kb_dir, file_hash, doc_name, meta)
        else:
            from openkb.storage.azure_blob import AzureBlobStorageBackend
            assert isinstance(backend, AzureBlobStorageBackend)
            async with backend.local_working_dir() as kb_dir:
                # Ensure raw file is present in the local working copy
                raw_file = kb_dir / "raw" / filename
                raw_file.parent.mkdir(parents=True, exist_ok=True)
                raw_file.write_bytes(raw_bytes)

                doc_name, skipped, meta = await _run_pipeline(raw_file, kb_dir, model)
                if not skipped:
                    await asyncio.to_thread(_register_hash, kb_dir, file_hash, doc_name, meta)
            # local_working_dir().__aexit__ uploads all changed files including hashes.json

    if skipped:
        return KBAddResult(
            status="skipped",
            doc_name=doc_name,
            message=f"Already in knowledge base: {filename}",
        )
    return KBAddResult(
        status="added",
        doc_name=doc_name,
        message=f"Document '{doc_name}' added to knowledge base.",
    )
