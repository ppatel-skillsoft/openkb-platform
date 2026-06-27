from __future__ import annotations

import logging
import re
from pathlib import Path

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.blob.aio import BlobServiceClient

from generator_api.exceptions import BlobSyncError

logger = logging.getLogger(__name__)

_FM_PATTERN = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_KV_PATTERN = re.compile(r'^(\w+):\s*"?(.*?)"?\s*$')


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract key:value pairs from YAML frontmatter (simple scalar values only)."""
    m = _FM_PATTERN.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = _KV_PATTERN.match(line)
        if kv:
            result[kv.group(1)] = kv.group(2).strip('"').strip("'")
    return result


def rebuild_index_md(wiki_dir: Path) -> None:
    """Rebuild ``index.md`` from all synced wiki pages.

    Each compiler-worker job writes a per-job ``index.md`` that only reflects
    the single document compiled in that session.  When the generator-api syncs
    all blobs, it gets the stale single-doc index.  This function regenerates a
    correct aggregate index by scanning every page in the wiki tree.

    Args:
        wiki_dir: Path to the local ``wiki/`` directory (e.g.
            ``scratch_dir/kb_slug/wiki``).
    """
    sections: dict[str, list[str]] = {
        "Documents": [],
        "Concepts": [],
        "Entities": [],
        "Explorations": [],
    }

    subdirs = {
        "Documents": (wiki_dir / "summaries", "summaries"),
        "Concepts": (wiki_dir / "concepts", "concepts"),
        "Entities": (wiki_dir / "entities", "entities"),
        "Explorations": (wiki_dir / "explorations", "explorations"),
    }

    for section, (subdir, prefix) in subdirs.items():
        if not subdir.is_dir():
            continue
        for path in sorted(subdir.glob("*.md")):
            slug = path.stem
            try:
                fm = _parse_frontmatter(path.read_text(encoding="utf-8"))
            except OSError:
                fm = {}
            description = fm.get("description", "")
            if section == "Documents":
                doc_type = fm.get("doc_type", "short")
                sections[section].append(
                    f"- [[{prefix}/{slug}]] ({doc_type}) — {description}"
                )
            elif section == "Entities":
                entity_type = fm.get("type", "")
                sections[section].append(
                    f"- [[{prefix}/{slug}]] ({entity_type}) — {description}"
                )
            else:
                sections[section].append(f"- [[{prefix}/{slug}]] — {description}")

    lines: list[str] = ["# Knowledge Base Index\n"]
    for section, items in sections.items():
        lines.append(f"## {section}")
        lines.extend(items)
        lines.append("")

    (wiki_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
    counts = {s: len(items) for s, items in sections.items()}
    logger.info(
        "Rebuilt index.md: %d docs, %d concepts, %d entities, %d explorations",
        counts["Documents"],
        counts["Concepts"],
        counts["Entities"],
        counts["Explorations"],
    )


async def delete_summary_blob(
    connection_string: str,
    container: str,
    doc_slug: str,
) -> None:
    """Delete the summary blob for *doc_slug* from *container*.

    The blob ``wiki/summaries/{doc_slug}.md`` is removed.  If it is already
    absent, the error is swallowed silently (idempotent).  Any other Azure
    SDK error is wrapped in :exc:`BlobSyncError`.

    Args:
        connection_string: Azure Blob Storage connection string.
        container: Container name (e.g. ``kb-<uuid>``).
        doc_slug: Document slug used as the blob filename stem.
    """
    blob_name = f"wiki/summaries/{doc_slug}.md"
    try:
        async with BlobServiceClient.from_connection_string(connection_string) as svc:
            blob_client = svc.get_container_client(container).get_blob_client(blob_name)
            await blob_client.delete_blob()
            logger.debug("Deleted summary blob %s/%s", container, blob_name)
    except ResourceNotFoundError:
        logger.debug("Summary blob %s/%s already absent — skipping", container, blob_name)
    except AzureError as exc:
        raise BlobSyncError(f"Failed to delete blob {container}/{blob_name}: {exc}") from exc


async def upload_index_to_blob(
    connection_string: str,
    container: str,
    index_path: Path,
) -> None:
    """Upload a rebuilt ``index.md`` to ``wiki/index.md`` in *container*.

    Args:
        connection_string: Azure Blob Storage connection string.
        container: Container name (e.g. ``kb-<uuid>``).
        index_path: Local :class:`~pathlib.Path` to the rebuilt index file.

    Raises:
        BlobSyncError: If the upload fails for any reason.
    """
    blob_name = "wiki/index.md"
    content = index_path.read_text(encoding="utf-8")
    try:
        async with BlobServiceClient.from_connection_string(connection_string) as svc:
            blob_client = svc.get_container_client(container).get_blob_client(blob_name)
            await blob_client.upload_blob(content, overwrite=True)
            logger.debug("Uploaded index to %s/%s", container, blob_name)
    except AzureError as exc:
        raise BlobSyncError(f"Failed to upload index to {container}/{blob_name}: {exc}") from exc


async def check_azurite(connection_string: str) -> str:
    """Probe Azurite by listing containers. Returns 'ok' or 'error: {msg}'."""
    try:
        async with BlobServiceClient.from_connection_string(connection_string) as svc:
            async for _ in svc.list_containers():
                break  # Just need to confirm connectivity
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Azurite health check failed: %s", exc)
        return f"error: {exc}"


async def sync_wiki_tree(
    connection_string: str,
    container: str,
    kb_blob_prefix: str,
    scratch_dir: Path,
) -> None:
    """Download all wiki blobs for a KB to *scratch_dir*/wiki/.

    Args:
        connection_string: Azure Blob Storage connection string.
        container: Container name (e.g. ``kb-<uuid>``).
        kb_blob_prefix: Blob name prefix pointing to the wiki tree
            (e.g. ``wiki/``). All blobs under this prefix are downloaded.
        scratch_dir: Per-request scratch directory; wiki files land in
            ``scratch_dir/wiki/``.

    Raises:
        BlobSyncError: If zero blobs are found or any download fails.
    """
    prefix = "wiki/"
    downloaded = 0

    try:
        async with BlobServiceClient.from_connection_string(connection_string) as svc:
            container_client = svc.get_container_client(container)

            async for blob in container_client.list_blobs(name_starts_with=prefix):
                blob_name: str = blob.name  # e.g. wiki/summaries/hello.md
                # Relative path under scratch_dir: keep the full blob_name so
                # the sidecar sees wiki/... at its root.
                dest = scratch_dir / blob_name
                dest.parent.mkdir(parents=True, exist_ok=True)

                blob_client = container_client.get_blob_client(blob_name)
                try:
                    stream = await blob_client.download_blob()
                    content = await stream.readall()
                    dest.write_bytes(content)
                    logger.debug("Synced blob %s → %s", blob_name, dest)
                    downloaded += 1
                except AzureError as exc:
                    raise BlobSyncError(
                        f"Failed to download blob {blob_name}: {exc}"
                    ) from exc

    except BlobSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BlobSyncError(f"Blob storage unavailable: {exc}") from exc

    if downloaded == 0:
        raise BlobSyncError(
            f"Wiki is empty for KB — no blobs found under {container}/{prefix}"
        )

    logger.info(
        "Synced %d wiki blobs from %s/%s → %s",
        downloaded,
        container,
        prefix,
        scratch_dir,
    )
