# Implementation Plan: Delete Document Endpoint

**Branch**: `feature/011-delete-document-endpoint` | **Date**: 2026-06-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/011-delete-document-endpoint/spec.md`

## Summary

Add `DELETE /kbs/{kb_id}/documents/{doc_id}` to `generator_api`. The endpoint soft-deletes the
document row (`deleted_at = NOW()`), removes the document's summary blob from Azure Blob Storage,
rebuilds and re-uploads the knowledge base `index.md` to reflect the deletion, and returns
`204 No Content`. No AI or LLM calls are made. The operation is idempotent: a second call for an
already-deleted document returns `204` without performing further storage or database work.

## Technical Context

**Language/Version**: Python 3.12 (`from __future__ import annotations` in every module)
**Primary Dependencies**: FastAPI 0.137.2, SQLAlchemy 2.0 (asyncio), asyncpg 0.30.0,
  azure-storage-blob 12.24.0, pytest + pytest-asyncio, ruff, bandit
**Storage**: PostgreSQL for document/KB metadata; Azure Blob Storage (Azurite locally)
  for wiki artefacts. Container per KB: `kb-{kb_id}` or `storage_container_path` field.
  Blob path convention: `wiki/summaries/{doc_slug}.md` within the container.
**Testing**: `pytest` (asyncio_mode=auto), `unittest.mock` for DB + blob; `httpx.AsyncClient`
  with `ASGITransport` for integration tests. `ruff` + `bandit` gates MUST pass before PR.
**Target Platform**: Docker Compose (local); AKS or Azure Container Apps (cloud)
**Project Type**: Multi-tenant SaaS platform — `generator_api` service only
**Performance Goals**: Deletion completes in under 5 seconds under normal load (SC-001)
**Constraints**: Per-KB isolation maintained at all times; no cross-KB data access
**Scale/Scope**: Single document deletion; no batch operation; no AI/LLM involvement

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design — see below.*

| Check | Principle | Status |
|-------|-----------|--------|
| Local Docker Compose stack runs end-to-end | I. Local-First | PASS — no new services; existing compose stack covers postgres + azurite |
| No secrets or API keys in source or config files | II. Security | PASS — storage credentials sourced from env vars via `get_settings()` |
| `bandit` passes with zero unresolved findings | II. Security / VIII. Test Discipline | PASS — no `eval`, subprocess, or shell calls; blob delete via Azure SDK |
| `ruff check` and `ruff format --check` pass | VIII. Test Discipline | PASS — enforced by CI gate; must be verified locally before PR |
| All new modules have corresponding test files | VIII. Test Discipline | PASS — `generator_api/service.py` covered by `tests/unit/generator_api/test_service.py`; route covered by `tests/integration/generator_api/test_delete_document.py` |
| Per-KB data and process isolation is maintained | IV. Isolation | PASS — ownership check (`kb_id + doc_id` in same query) prevents cross-KB deletion |
| Storage backend uses abstract interface (not cloud-specific) | VI. Configurability | PARTIAL — existing `generator_api/blob.py` is Azure-specific; this feature adds two new blob helper functions following the same pattern. Full abstraction deferred to a future refactor. |
| Logging uses `logging.getLogger(__name__)`, not `print` | III. Observability | PASS — new service module uses module-level logger |
| `/health` and `/ready` endpoints present (if new service) | III. Observability | N/A — no new service; existing `/health` endpoint unchanged |
| `openkb-core` dependency references a pinned git tag | II. Security | PASS — `pyproject.toml` already pins `openkb-core@v0.1.0`; no change required |
| Feature branch targets `develop`, not `main` | Git Flow | PASS — branch is `feature/011-delete-document-endpoint` |
| All new behaviour covered by tests (unit + integration) | VIII. Test Discipline | PASS — see test plan in Phase 1 design |

**Violations requiring documented justification**:

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Storage backend not abstracted (azure-specific in `blob.py`) | New blob helper functions follow the existing concrete pattern already established in `blob.py` | Introducing an abstract storage interface is a cross-cutting refactor out of scope for this feature; tracked as future work |
| Authentication not enforced | Spec explicitly defers auth to a future iteration; documented in spec security section | Implementing auth in this feature would block delivery and is not scoped |

## Project Structure

### Documentation (this feature)

```text
specs/011-delete-document-endpoint/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── contracts/
│   └── delete-document.md   # DELETE endpoint contract
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks — not created by /speckit.plan)
```

### Source Code Changes

```text
generator_api/
├── exceptions.py        # ADD: DocumentNotFoundError
├── service.py           # NEW: service_delete_document()
├── blob.py              # ADD: delete_summary_blob(), upload_index_to_blob()
├── router.py            # ADD: DELETE /kbs/{kb_id}/documents/{doc_id} route
└── app.py               # ADD: exception_handler for DocumentNotFoundError → 404

tests/
├── unit/
│   └── generator_api/
│       ├── __init__.py              # NEW (empty)
│       ├── test_service.py          # NEW: unit tests for service_delete_document
│       └── test_blob_helpers.py     # NEW: unit tests for delete_summary_blob + upload_index_to_blob
└── integration/
    └── generator_api/
        ├── __init__.py              # NEW (empty)
        ├── conftest.py              # NEW: app fixture, mock DB/blob fixtures
        └── test_delete_document.py  # NEW: integration tests via ASGITransport + httpx
```

**Structure Decision**: `generator_api` service follows the existing flat-module layout
(`exceptions.py`, `blob.py`, `router.py`, `app.py`). A new `service.py` module is introduced
to satisfy FR-011 (no business logic in the route handler). Tests mirror the source tree under
`tests/unit/generator_api/` and `tests/integration/generator_api/`.

## Phase 0 Research Findings

See `research.md` for full details. Key decisions:

| Question | Decision | Rationale |
|----------|----------|-----------|
| Actual summary blob path | `wiki/summaries/{doc_slug}.md` within the KB container | Confirmed by `sync_wiki_tree` in `blob.py` which lists under `wiki/` prefix; the `{kb_id}` in the plan prompt refers to the container name, not a blob path prefix |
| Index rebuild approach | Sync wiki tree to temp dir → `rebuild_index_md` → `upload_index_to_blob` | Reuses existing `rebuild_index_md`; consistent with query route pattern; temp dir cleaned up in finally block |
| 0-blob edge case | Service catches `BlobSyncError` when no wiki blobs remain; writes empty-section index and uploads | Ensures index.md is always present even when all docs deleted; downstream consumers receive an empty-but-valid index |
| New blob helpers location | `generator_api/blob.py` | Co-located with existing blob utilities; no new module needed |
| Service module location | `generator_api/service.py` | Satisfies FR-011 separation; keeps `router.py` thin |
| `DocumentNotFoundError` args | `DocumentNotFoundError(doc_id, kb_id)` mirrors `KBNotFoundError(kb_id)` pattern | Consistent exception design; includes both IDs for logging/debugging |
