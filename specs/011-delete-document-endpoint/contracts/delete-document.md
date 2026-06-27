# API Contract: Delete Document

**Feature**: 011 — Delete Document Endpoint
**Endpoint**: `DELETE /kbs/{kb_id}/documents/{doc_id}`
**Service**: `generator_api`
**Date**: 2026-06-27

---

## Endpoint Summary

Soft-deletes a document from a knowledge base. Removes the document's compiled summary blob
from Azure Blob Storage and rebuilds the knowledge base index. Returns `204 No Content` on
success. Idempotent: returns `204` if the document is already deleted.

---

## Request

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `kb_id` | `UUID` (string) | Yes | Knowledge base identifier |
| `doc_id` | `UUID` (string) | Yes | Document identifier |

### Headers

| Header | Value | Required | Notes |
|--------|-------|----------|-------|
| (none required) | — | — | Authentication deferred to a future iteration |

### Request Body

None.

### Example Request

```http
DELETE /kbs/3fa85f64-5717-4562-b3fc-2c963f66afa6/documents/8d3f2c1a-0000-4b5e-9c7d-1234abcd5678 HTTP/1.1
Host: generator-api.example.com
```

---

## Responses

### 204 No Content — Successful Deletion

The document was soft-deleted (or was already soft-deleted). No response body.

```http
HTTP/1.1 204 No Content
```

### 404 Not Found — Knowledge Base Not Found

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{
  "detail": "Knowledge base 3fa85f64-5717-4562-b3fc-2c963f66afa6 not found"
}
```

**Triggers**: `kb_id` does not exist in the database, or the knowledge base is itself
soft-deleted.

### 404 Not Found — Document Not Found

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

{
  "detail": "Document 8d3f2c1a-0000-4b5e-9c7d-1234abcd5678 not found in knowledge base 3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

**Triggers**: `doc_id` does not exist within `kb_id`, or the document belongs to a different
knowledge base (cross-KB access returns `404`, not `403`).

### 422 Unprocessable Entity — Invalid UUID

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/json

{
  "detail": [
    {
      "type": "uuid_parsing",
      "loc": ["path", "kb_id"],
      "msg": "Input should be a valid UUID ...",
      "input": "not-a-uuid"
    }
  ]
}
```

**Triggers**: `kb_id` or `doc_id` is not a valid UUID string. Handled automatically by
FastAPI's path parameter type coercion before any handler logic runs.

### 500 Internal Server Error — Storage Failure

```http
HTTP/1.1 500 Internal Server Error
Content-Type: application/json

{
  "detail": "Blob storage unavailable: ..."
}
```

**Triggers**: Azure Blob Storage is unreachable or returns an unexpected error after the DB
soft-delete has already been committed. The document is soft-deleted in the DB; the index may
be stale. Callers should retry.

---

## Behaviour Contract

| Scenario | Precondition | Expected Response | Side Effects |
|----------|-------------|-------------------|--------------|
| Happy path | KB exists, doc exists and is active | `204` | `deleted_at` set, summary blob deleted, `index.md` rebuilt |
| Idempotent re-delete | KB exists, doc already soft-deleted | `204` | No DB update, no blob ops, no index rebuild |
| KB not found | `kb_id` absent or soft-deleted | `404` | None |
| Doc not found | `doc_id` absent or in different KB | `404` | None |
| Invalid UUID | Either path parameter is not a UUID | `422` | None |
| Blob already absent | Summary blob was already missing | `204` | `deleted_at` set, missing blob silently skipped, `index.md` rebuilt |
| All docs deleted | KB exists, all docs now soft-deleted | `204` | `deleted_at` set, empty `index.md` uploaded |
| Storage unreachable | Azure error after DB commit | `500` | `deleted_at` already set; `index.md` may be stale |

---

## Idempotency

The endpoint is idempotent per HTTP DELETE semantics. Sending the same request N times yields
`204 No Content` on every call. The second and subsequent calls do not modify the database or
blob storage.

---

## Performance

- Target response time: under 5 seconds under normal load (SC-001)
- No AI or LLM calls are made
- Main latency contributors: DB round-trips (2), blob delete (1), wiki sync + index upload
  (proportional to KB size)

---

## Out of Scope

- Hard delete of the database row
- Deletion of concept or entity blobs (FR-004: intentionally preserved)
- Authentication or authorisation (deferred)
- Cascade deletion of a knowledge base and all its documents
