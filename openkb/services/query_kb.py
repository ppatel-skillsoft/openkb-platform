from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from openkb.services import KBNotFoundError, KBQueryResult, LLMError
from openkb.storage.base import StorageBackend

logger = logging.getLogger(__name__)


async def service_query_kb(
    backend: StorageBackend,
    kb_name: str,
    question: str,
    save: bool = False,
) -> KBQueryResult:
    """Answer *question* against an existing KB.

    Raises:
        KBNotFoundError: if ``.openkb/config.yaml`` is absent.
        LLMError: if the LLM call fails.
    """
    if not await backend.exists(".openkb/config.yaml"):
        raise KBNotFoundError(kb_name)

    # Load config to get model + language
    config_bytes = await backend.read_bytes(".openkb/config.yaml")
    config = yaml.safe_load(config_bytes) or {}
    from openkb.config import DEFAULT_CONFIG
    model: str = config.get("model", DEFAULT_CONFIG["model"])

    from openkb.agent.query import run_query
    from openkb.cli import _setup_llm_key

    try:
        from openkb.storage.local import LocalStorageBackend
        if isinstance(backend, LocalStorageBackend):
            _setup_llm_key(backend.kb_dir)
            answer = await run_query(question, backend.kb_dir, model, stream=False)
            kb_dir_for_save = backend.kb_dir
        else:
            # Azure: materialise blobs to a temp dir for the compiler
            from openkb.storage.azure_blob import AzureBlobStorageBackend
            assert isinstance(backend, AzureBlobStorageBackend)
            async with backend.local_working_dir() as kb_dir:
                _setup_llm_key(None)
                answer = await run_query(question, kb_dir, model, stream=False)
                kb_dir_for_save = None  # will write via backend directly

    except Exception as exc:
        # Surface only LLM/agent errors; re-raise everything else
        exc_str = str(exc)
        if any(k in exc_str.lower() for k in ("api key", "authentication", "rate limit", "quota", "litellm")):
            raise LLMError(exc_str) from exc
        raise

    saved_to: str | None = None
    if save and answer:
        slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:60]
        explore_rel = f"wiki/explorations/{slug}.md"
        content = f'---\nquery: "{question}"\n---\n\n{answer}\n'

        # Strip ghost wikilinks (same logic as CLI)
        if kb_dir_for_save is not None:
            from openkb.lint import list_existing_wiki_targets, strip_ghost_wikilinks
            known = list_existing_wiki_targets(kb_dir_for_save / "wiki")
            content_body, _ = strip_ghost_wikilinks(answer, known)
            content = f'---\nquery: "{question}"\n---\n\n{content_body}\n'

        await backend.write_text(explore_rel, content)
        saved_to = explore_rel

    return KBQueryResult(answer=answer or "", saved_to=saved_to)
