# Research: Delete Document Endpoint (Feature 011)

**Phase**: 0 — Pre-design research
**Branch**: `feature/011-delete-document-endpoint`
**Date**: 2026-06-27

---

## 1. Summary Blob Path Convention

**Question**: The plan prompt described the summary blob path as `{kb_id}/summaries/{doc_slug}.md`.
Is this a full blob URL, or a container-relative path?

**Decision**: `wiki/summaries/{doc_slug}.md` (container-relative path within the KB container)

**Rationale**: Inspection of `generator_api/blob.py` `sync_wiki_tree()` confirms that all wiki
blobs live under the `wiki/` prefix within a per-KB container named `kb-{kb_id}` (or the value
of `storage_container_path`). The `{kb_id}` in the original description refers to the *container
name*, not a path prefix. The actual blob name inside the container is
`wiki/summaries/{doc_slug}.md`. The same convention is visible in the `rebuild_index_md`
subdirs mapping: `"Documents": (wiki_dir / "summaries", "summaries")`.

**Alternatives considered**:
- Treating `{kb_id}/summaries/{doc_slug}.md` as a cross-container path — rejected; the Azure SDK
  calls in `blob.py` always operate within a single container, splitting container name from blob
  name at the call site.

---

## 2. Index Rebuild Strategy

**Question**: After soft-deleting a document and removing its summary blob, how should the
`index.md` be rebuilt without invoking AI/LLM services?

**Decision**: Sync the remaining wiki blobs to a temporary local directory using the existing
`sync_wiki_tree()`, run the existing `rebuild_index_md()` against the local tree, then upload
the result via a new `upload_index_to_blob()` helper.

**Rationale**:
- `rebuild_index_md()` already handles all four sections (Documents, Concepts, Entities,
  Explorations) and reads YAML frontmatter (`description`, `doc_type`, `type`) from each blob.
  Reusing it ensures the rebuilt index is structurally identical to what the compiler worker
  produces, so downstream consumers (MCP server, query endpoint) receive a consistent format.
- The sync → rebuild → upload pipeline is already proven by the query route; the delete
  service follows the same scratch-dir pattern with a `try/finally` cleanup.
- The deleted summary blob is removed from Blob Storage *before* `sync_wiki_tree()` runs, so
  the local tree will not contain it and `rebuild_index_md()` will correctly exclude it.

**Alternatives considered**:
- **DB-driven index rebuild**: query non-deleted documents from Postgres, build the Documents
  section programmatically. Rejected because `rebuild_index_md()` reads frontmatter
  (`description`, `doc_type`) that is not stored in the `documents` DB table; we would lose
  this metadata or need a schema change. Considered as a future optimisation.
- **Blob-listing without download**: list blob names under `wiki/summaries/` in Azure and build
  the Documents section from slug names only (no frontmatter). Rejected because it would produce
  an incomplete index (missing `description` and `doc_type` fields) and would be inconsistent
  with the compiler-worker output format.

---

## 3. Zero-Blob Edge Case in `sync_wiki_tree`

**Question**: `sync_wiki_tree()` raises `BlobSyncError` if zero blobs are found. What happens if
all documents have been deleted and there are no remaining `wiki/` blobs (e.g., a KB with no
concepts or entities)?

**Decision**: The service catches `BlobSyncError` raised by `sync_wiki_tree()`, checks whether
the error message contains "empty" (the sentinel phrase from `blob.py`), and if so proceeds to
write an empty-section `index.md` to the scratch dir and uploads it. Any other `BlobSyncError`
(e.g., storage unreachable) is re-raised as a 500-class error.

**Rationale**: FR-005 requires the index to always be rebuilt after deletion. An empty KB is a
valid state (all documents soft-deleted) and must produce a valid but empty `index.md` rather
than failing. Downstream consumers already handle empty indexes gracefully.

**Implementation note**: The `BlobSyncError` message from `blob.py` for the empty case is:
`"Wiki is empty for KB — no blobs found under {container}/wiki/"`. The service should match on
`"no blobs found"` or an empty-result flag rather than the exact string to avoid brittleness.
A cleaner future option is to add a `min_blobs: int = 1` parameter to `sync_wiki_tree()`, but
that change is deferred to avoid scope creep.

---

## 4. New Blob Helper Functions

**Question**: What new functions are needed in `generator_api/blob.py`?

**Decision**: Two new async functions:

```python
async def delete_summary_blob(
    connection_string: str,
    container: str,
    doc_slug: str,
) -> None:
    """Delete wiki/summaries/{doc_slug}.md from blob storage.

    Silently succeeds if the blob does not exist (already deleted).
    Raises BlobSyncError on unexpected Azure errors.
    """

async def upload_index_to_blob(
    connection_string: str,
    container: str,
    index_path: Path,
) -> None:
    """Upload a local index.md to wiki/index.md in the container.

    Overwrites any existing index.
    Raises BlobSyncError on Azure errors.
    """
```

**Rationale**:
- `delete_summary_blob`: encapsulates the `ResourceNotFoundError` swallowing (blob already gone
  is idempotent) and the `BlobSyncError` wrapping for unexpected errors. The silent-success on
  404 is required by the spec edge case: "if the summary blob is already absent, the operation
  should still succeed."
- `upload_index_to_blob`: the complement of `sync_wiki_tree`; uploads a single rebuilt
  `index.md`. No equivalent function currently exists in `blob.py`.

**Alternatives considered**:
- Adding `get_container_client()` as a shared helper and having callers manage blob clients
  directly — rejected because it leaks Azure SDK types into the service layer and makes mocking
  harder in unit tests.

---

## 5. Service Module Design

**Question**: Should `service_delete_document` live in `generator_api/service.py` (new module)
or be added as a helper function at the bottom of `router.py`?

**Decision**: New module `generator_api/service.py`.

**Rationale**: FR-011 mandates that the route handler contains no business logic. Placing the
service function in `router.py` would co-locate business and routing logic and make the file
harder to test in isolation. A dedicated `service.py` mirrors common FastAPI project structure
and is already the right abstraction boundary given that the function has its own DB, blob, and
scratch-dir concerns.

**Service function signature**:

```python
async def service_delete_document(
    kb_id: str,
    doc_id: str,
    db: AsyncSession,
    connection_string: str,
) -> None:
    """Soft-delete a document, remove its summary blob, and rebuild the KB index.

    Raises:
        KBNotFoundError: if kb_id does not exist or is itself soft-deleted.
        DocumentNotFoundError: if doc_id does not exist within kb_id.
        BlobSyncError: if blob storage operations fail after the DB soft-delete.
    Returns:
        None (idempotent: already-deleted doc returns without error).
    """
```

**Idempotency**: The function checks `deleted_at IS NOT NULL` on the document row after the
ownership check. If the document is already soft-deleted, it returns immediately without
performing any storage operations. This satisfies FR-008 and SC-003.

---

## 6. Exception Design

**Question**: What does `DocumentNotFoundError` look like, and how is it wired to the HTTP layer?

**Decision**:

```python
# generator_api/exceptions.py (addition)
class DocumentNotFoundError(Exception):
    def __init__(self, doc_id: str, kb_id: str) -> None:
        super().__init__(f"Document {doc_id} not found in knowledge base {kb_id}")
        self.doc_id = doc_id
        self.kb_id = kb_id
```

Registered in `app.py` alongside the existing exception handlers:

```python
@app.exception_handler(DocumentNotFoundError)
async def _doc_not_found(request: Request, exc: DocumentNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})
```

**Rationale**: Mirrors the `KBNotFoundError` pattern already in the codebase. Both IDs are
stored as attributes to support structured logging in the service layer. The `app.py` handler
maps the exception to a `404` response with a `detail` key, consistent with all other error
responses in the API.

**Alternatives considered**:
- Catching the exception in the route handler and returning `JSONResponse` inline — rejected
  because centralising error translation in `app.py` is already the established pattern and
  keeps route handlers free of HTTP-response construction logic.

---

## 7. Ownership Validation Query

**Question**: How do we ensure a document belongs to the specified KB in a single DB round-trip?

**Decision**: Use a single `SELECT` with both `id = :doc_id AND kb_id = :kb_id`:

```sql
SELECT id, slug, deleted_at
FROM documents
WHERE id = :doc_id AND kb_id = :kb_id
```

If the row is `None`, raise `DocumentNotFoundError(doc_id, kb_id)`. This covers both
"document does not exist" and "document exists but belongs to a different KB" — both cases
correctly surface as `404` per the spec's isolation requirement.

**Rationale**: A single query is simpler and avoids a TOCTOU window between a "does doc exist?"
check and a separate "does it belong to this KB?" check. It also prevents leaking information
about documents from other KBs (returning 404 rather than 403 for cross-KB access is the
correct approach for multi-tenant APIs where callers should not be able to enumerate other
KBs' documents).

---

## 8. Soft-Delete SQL Pattern

**Question**: Should the `UPDATE` use `SET deleted_at = NOW()` or `SET deleted_at = CURRENT_TIMESTAMP`?

**Decision**: `SET deleted_at = timezone('utc', NOW())` — UTC timestamp, consistent with how the
`compiler_worker` records timestamps (verified by reviewing `compiler_worker/` DB operations which
use UTC-aware datetimes).

**Rationale**: UTC timestamps avoid timezone ambiguity. PostgreSQL's `NOW()` returns
`timestamp with time zone` based on the session timezone; using `timezone('utc', NOW())` ensures
the stored value is always UTC regardless of database server timezone configuration.

---

## 9. Test Strategy

**Question**: What test fixtures and mock strategies should be used?

**Decision**:

**Unit tests** (`tests/unit/generator_api/`):
- `test_service.py`: mock `AsyncSession` (using `AsyncMock` and `MagicMock`) and blob helper
  functions. Test: success path, idempotent delete (already deleted), KB not found, doc not
  found, doc in different KB (not found), blob already gone (silent success), blob sync error
  after soft-delete (surfaces as 500).
- `test_blob_helpers.py`: mock `BlobServiceClient` context manager; test `delete_summary_blob`
  (blob exists, blob missing → silent, Azure error → `BlobSyncError`) and `upload_index_to_blob`
  (success, Azure error → `BlobSyncError`).

**Integration tests** (`tests/integration/generator_api/`):
- `test_delete_document.py`: use `httpx.AsyncClient` with `ASGITransport(app=app)` against the
  FastAPI app created by `create_app()`. Override FastAPI dependencies (`get_db`, `get_settings`)
  using `app.dependency_overrides`. Mock `service_delete_document` at the import boundary.
  Tests: 204 success, 204 idempotent, 404 KB not found, 404 doc not found, 422 invalid UUID.

**Fixtures**: No Postgres or Azurite required for unit or integration tests (all mocked).
  Real-DB integration tests against Azurite/Postgres are deferred to `tests/isolation/` in a
  future iteration.
