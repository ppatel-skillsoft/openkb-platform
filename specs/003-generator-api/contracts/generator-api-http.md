# Contract: Generator API HTTP Interface

**Branch**: `004-generator-api` | **Date**: 2026-06-21
**Service**: `generator_api` — Phase 0 query proxy
**Base URL (local)**: `http://localhost:8001`

---

## Purpose

Defines the public HTTP API surface exposed by the generator-api service. Phase 0 exposes two
endpoints: a query endpoint and a health-check endpoint. No authentication is required.

---

## Endpoints

### `POST /kbs/{kb_id}/query`

Answer a natural-language question against a compiled knowledge base.

**Path parameter**:

| Parameter | Type | Validation |
|-----------|------|------------|
| `kb_id` | UUID | FastAPI `uuid.UUID` type — rejects non-UUID (including path traversal) |

**Request body** (`application/json`):

```json
{
  "question": "string",
  "save": false
}
```

| Field | Type | Required | Validation | Notes |
|-------|------|----------|------------|-------|
| `question` | string | ✅ | Non-empty after strip; max 8000 chars | Passed verbatim to sidecar |
| `save` | boolean | No | — | Accepted; no-op in Phase 0; always forwarded as `false` to sidecar |

**Response** `200 OK` (`application/json`):

```json
{
  "answer": "string",
  "citations": [],
  "tokens_used": 0
}
```

| Field | Type | Notes |
|-------|------|-------|
| `answer` | string | Non-empty; verbatim from sidecar |
| `citations` | array | Verbatim from sidecar. Phase 0: always `[]` — sidecar does not yet return structured citations. Structure present per spec. |
| `tokens_used` | integer | Phase 0: always `0` — sidecar does not yet return token counts |

**Error responses**:

| HTTP | Condition | Body |
|------|-----------|------|
| 422 | `kb_id` is not a valid UUID | `{ "detail": "..." }` |
| 422 | `question` is missing or blank | `{ "detail": "question: field required" }` |
| 422 | `question` exceeds 8000 characters | `{ "detail": "question: must be 8000 characters or fewer" }` |
| 404 | KB does not exist in `knowledge_bases` table (or is soft-deleted) | `{ "detail": "Knowledge base {kb_id} not found" }` |
| 409 | KB exists but has no documents with `status = 'complete'` | `{ "detail": "Knowledge base {kb_id} has no compiled documents" }` |
| 503 | Azurite / Blob Storage unreachable | `{ "detail": "Blob storage unavailable: {message}" }` |
| 503 | Wiki tree sync failed (partial download) | `{ "detail": "Wiki sync failed: {message}" }` |
| 502 | Sidecar failed to start | `{ "detail": "Sidecar failed to start: {message}" }` |
| 502 | Sidecar returned an error on init or query | `{ "detail": "Sidecar error: {message}" }` |
| 504 | Sidecar did not respond within `GENERATOR_REQUEST_TIMEOUT` seconds | `{ "detail": "Query timed out after {N}s" }` |
| 500 | Unexpected internal error | `{ "detail": "Internal server error" }` |

**Observability**: Every request logs at INFO level:
```
POST /kbs/{kb_id}/query question_length={N} elapsed_ms={N} status={200|4xx|5xx}
```

---

### `GET /health`

Liveness and dependency health check.

**Response** `200 OK` — all dependencies reachable:

```json
{
  "status": "ok",
  "postgres": "ok",
  "azurite": "ok"
}
```

**Response** `503 Service Unavailable` — one or more dependencies unreachable:

```json
{
  "status": "degraded",
  "postgres": "ok|error",
  "azurite": "error",
  "detail": "Azurite unreachable: connection refused"
}
```

**Probes**:
- `postgres`: execute `SELECT 1` via the async session factory
- `azurite`: call `BlobServiceClient.list_containers()` (returns after first page)

This endpoint is used by Docker Compose `HEALTHCHECK` and by `GET /health` from external tools.

---

## OpenAPI / Docs

FastAPI auto-generates OpenAPI schema at `GET /openapi.json` and Swagger UI at `GET /docs`.
These are available in development; may be disabled in production via `docs_url=None`.

---

## Versioning

No API versioning in Phase 0. URL structure (`/kbs/{kb_id}/query`) is compatible with the
full Phase 1+ API design (`06-api-spec.md`) — no breaking changes anticipated at Phase 1.

---

## Security

No authentication or authorisation in Phase 0. The service is internal-use only and bound to
the Docker Compose network or `localhost` when run standalone. Do not expose port 8001 publicly.
