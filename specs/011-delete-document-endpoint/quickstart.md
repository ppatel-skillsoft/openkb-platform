# Quickstart: Delete Document Endpoint (Feature 011)

**Feature**: 011 — Delete Document Endpoint
**Branch**: `feature/011-delete-document-endpoint`
**Date**: 2026-06-27

---

## Prerequisites

- Python 3.12+
- `uv` package manager
- Docker + Docker Compose (for local stack)
- Local environment file (`.env`) with at minimum:
  ```
  DATABASE_URL=postgresql+asyncpg://openkb:openkb@localhost:5432/openkb
  AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=...;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1
  LLM_API_KEY=sk-placeholder
  ```

---

## 1. Start the Local Stack

```bash
docker compose up -d
```

Brings up Postgres, Azurite (Azure Blob emulator), the `generator_api`, and the
`compiler_worker`. Wait until `generator-api-1` logs `"Generator API v... starting — all dependencies reachable"`.

---

## 2. Install Dependencies

```bash
uv sync
```

---

## 3. Run All Tests

```bash
uv run pytest
```

Expected: all tests pass, including the new tests in
`tests/unit/generator_api/` and `tests/integration/generator_api/`.

---

## 4. Run Quality Gates

```bash
uv run ruff check .
uv run ruff format --check .
uv run bandit -r .
```

All three must report zero findings before opening a pull request.

---

## 5. Exercise the Endpoint Manually

### Create a test KB and document (example using psql)

```sql
-- Connect to the local Postgres instance
-- docker compose exec postgres psql -U openkb openkb

INSERT INTO knowledge_bases (id, name, slug, status)
VALUES ('aaaaaaaa-0000-0000-0000-000000000001', 'Test KB', 'test-kb', 'active');

INSERT INTO documents (id, kb_id, slug, source_type, source_uri, original_filename, status)
VALUES (
    'bbbbbbbb-0000-0000-0000-000000000001',
    'aaaaaaaa-0000-0000-0000-000000000001',
    'my-document',
    'md',
    'kb-aaaaaaaa-0000-0000-0000-000000000001/raw/my-document.md',
    'my-document.md',
    'complete'
);
```

### Upload a placeholder summary blob (using Azure CLI against Azurite)

```bash
az storage blob upload \
  --connection-string "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1" \
  --container-name "kb-aaaaaaaa-0000-0000-0000-000000000001" \
  --name "wiki/summaries/my-document.md" \
  --data "# My Document\ndescription: A test document\ndoc_type: short" \
  --overwrite
```

### Send the delete request

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -X DELETE \
  http://localhost:8000/kbs/aaaaaaaa-0000-0000-0000-000000000001/documents/bbbbbbbb-0000-0000-0000-000000000001
```

Expected output: `204`

### Verify the document is soft-deleted

```sql
SELECT id, slug, deleted_at FROM documents
WHERE id = 'bbbbbbbb-0000-0000-0000-000000000001';
-- deleted_at should now be a UTC timestamp
```

### Verify the summary blob is gone

```bash
az storage blob show \
  --connection-string "..." \
  --container-name "kb-aaaaaaaa-0000-0000-0000-000000000001" \
  --name "wiki/summaries/my-document.md"
# Expected: BlobNotFound error (404)
```

### Verify idempotency (send the same request again)

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -X DELETE \
  http://localhost:8000/kbs/aaaaaaaa-0000-0000-0000-000000000001/documents/bbbbbbbb-0000-0000-0000-000000000001
```

Expected output: `204` (again, with no storage changes)

---

## 6. Key Files Modified / Created

| File | Change |
|------|--------|
| `generator_api/exceptions.py` | Add `DocumentNotFoundError` |
| `generator_api/blob.py` | Add `delete_summary_blob()`, `upload_index_to_blob()` |
| `generator_api/service.py` | New — `service_delete_document()` |
| `generator_api/router.py` | Add `DELETE /kbs/{kb_id}/documents/{doc_id}` route |
| `generator_api/app.py` | Add exception handler for `DocumentNotFoundError` |
| `tests/unit/generator_api/__init__.py` | New — empty |
| `tests/unit/generator_api/test_service.py` | New — unit tests |
| `tests/unit/generator_api/test_blob_helpers.py` | New — unit tests |
| `tests/integration/generator_api/__init__.py` | New — empty |
| `tests/integration/generator_api/conftest.py` | New — app + mock fixtures |
| `tests/integration/generator_api/test_delete_document.py` | New — integration tests |
