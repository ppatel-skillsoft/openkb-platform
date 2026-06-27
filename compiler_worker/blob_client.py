from __future__ import annotations

import logging
from pathlib import Path

from azure.storage.blob import BlobServiceClient

logger = logging.getLogger(__name__)


class BlobStorageClient:
    """Thin wrapper around Azure Blob Storage SDK.

    Blob paths follow the convention ``{container}/{blob_name}`` where
    ``container`` is the first path component (e.g. ``kb-<uuid>``) and
    ``blob_name`` is everything after the first ``/``.
    """

    def __init__(self, connection_string: str) -> None:
        self._service = BlobServiceClient.from_connection_string(connection_string)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split(blob_path: str) -> tuple[str, str]:
        """Split ``{container}/{blob_name}`` into ``(container, blob_name)``."""
        container, _, blob_name = blob_path.partition("/")
        return container, blob_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download_to_file(self, blob_path: str, dest: Path) -> None:
        """Download *blob_path* to *dest* on the local filesystem.

        Raises ``azure.core.exceptions.ResourceNotFoundError`` if the blob
        does not exist (propagated transparently to callers).
        """
        container, blob_name = self._split(blob_path)
        blob_client = self._service.get_blob_client(container=container, blob=blob_name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            stream = blob_client.download_blob()
            stream.readinto(fh)
        logger.debug("Downloaded blob %s → %s", blob_path, dest)

    def upload_from_file(self, blob_path: str, src: Path) -> None:
        """Upload *src* to *blob_path* in Blob Storage (overwrites if present)."""
        container, blob_name = self._split(blob_path)
        blob_client = self._service.get_blob_client(container=container, blob=blob_name)
        with src.open("rb") as fh:
            blob_client.upload_blob(fh, overwrite=True)
        logger.debug("Uploaded %s → blob %s", src, blob_path)

    def rebuild_and_upload_index(self, container: str) -> None:
        """Build a comprehensive wiki/index.md from all compiled blobs and upload it.

        Lists every blob under wiki/summaries/, wiki/concepts/, and wiki/entities/
        in *container*, downloads each one, parses YAML front-matter for title and
        description, then writes and uploads a fresh wiki/index.md.

        Called by the compiler worker after every successful compilation so that
        blob storage always holds an aggregate index that covers all compiled
        documents — not just the most recently compiled one.
        """
        import re

        _FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
        _TITLE_RE = re.compile(r"^title\s*:\s*(.+)$", re.MULTILINE)
        _DESC_RE = re.compile(r"^description\s*:\s*(.+)$", re.MULTILINE)

        section_prefixes = {
            "Documents": "wiki/summaries/",
            "Concepts": "wiki/concepts/",
            "Entities": "wiki/entities/",
        }

        sections: dict[str, list[tuple[str, str, str]]] = {s: [] for s in section_prefixes}

        container_client = self._service.get_container_client(container)

        for section, prefix in section_prefixes.items():
            for blob_props in container_client.list_blobs(name_starts_with=prefix):
                blob_name: str = blob_props.name
                if not blob_name.endswith(".md"):
                    continue
                try:
                    content = (
                        container_client.get_blob_client(blob_name)
                        .download_blob()
                        .readall()
                        .decode("utf-8")
                    )
                except Exception as exc:
                    logger.warning("Skipping blob %s during index rebuild: %s", blob_name, exc)
                    continue

                fm_match = _FM_RE.match(content)
                fm_block = fm_match.group(1) if fm_match else ""
                title_m = _TITLE_RE.search(fm_block)
                desc_m = _DESC_RE.search(fm_block)

                stem = blob_name[len(prefix):].removesuffix(".md")
                subdir = prefix.removeprefix("wiki/").rstrip("/")
                slug = f"{subdir}/{stem}"
                title = title_m.group(1).strip() if title_m else stem
                description = desc_m.group(1).strip() if desc_m else ""
                sections[section].append((slug, title, description))

        lines: list[str] = ["# Knowledge Base Index\n"]
        for section, entries in sections.items():
            lines.append(f"\n## {section}")
            if entries:
                for slug, title, description in entries:
                    suffix = f" — {description}" if description else ""
                    lines.append(f"- **{title}** (`{slug}`){suffix}")
            else:
                lines.append("")

        index_content = ("\n".join(lines) + "\n").encode("utf-8")
        container_client.get_blob_client("wiki/index.md").upload_blob(
            index_content, overwrite=True
        )
        total = sum(len(v) for v in sections.values())
        logger.info(
            "Rebuilt and uploaded wiki/index.md for container %s (%d entries)", container, total
        )

    def ensure_container(self, container: str) -> None:
        """Create *container* if it does not already exist."""
        container_client = self._service.get_container_client(container)
        try:
            container_client.create_container()
            logger.debug("Created blob container: %s", container)
        except Exception as exc:
            # ResourceExistsError is expected on subsequent calls; swallow it.
            if (
                "ContainerAlreadyExists" in type(exc).__name__
                or "already exists" in str(exc).lower()
            ):
                logger.debug("Blob container already exists: %s", container)
            else:
                raise
