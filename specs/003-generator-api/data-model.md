# Data Model: Phase 0 Generator API Service

**Branch**: `004-generator-api` | **Date**: 2026-06-21
**Source**: Spec `/specs/003-generator-api/spec.md`

---

## Overview

The generator-api makes **no writes to any database table** in Phase 0. It reads from two inherited
tables (`knowledge_bases`, `documents`) and orchestrates an in-memory/filesystem workflow. The
entities described here are the logical objects the service operates on.

For the Postgres schema, see: [`specs/001-phase0-postgres-schema/data-model.md`](../../001-phase0-postgres-schema/data-model.md)

---

## Inherited Database Entities (read-only)

### KnowledgeBase

Source: `knowledge_bases` table.
Fields consumed by generator-api:

| Field | Type | Use |
|-------|------|-----|
| `id` | UUID | Looked up from URL path parameter |
| `slug` | TEXT | Used as sidecar `kb_name` and scratch dir segment |
| `storage_container_path` | TEXT | Blob prefix root for wiki tree sync (e.g. `kb-{id}`) |
| `status` | TEXT | Validated: reject `archived` (optional guard) |
| `deleted_at` | TIMESTAMPTZ | Must be NULL — soft-deleted KBs are rejected |

**Pre-flight query**:
```sql
SELECT id, slug, storage_container_path, status
FROM knowledge_bases
WHERE id = :kb_id AND deleted_at IS NULL
```
Returns `None` → HTTP 404.

---

### Document

Source: `documents` table.
Fields consumed by generator-api:

| Field | Type | Use |
|-------|------|-----|
| `kb_id` | UUID | Filter by KB |
| `status` | TEXT | Must have ≥ 1 row with `status = 'complete'` |
| `deleted_at` | TIMESTAMPTZ | Exclude soft-deleted rows |

**Pre-flight query**:
```sql
SELECT COUNT(*) FROM documents
WHERE kb_id = :kb_id
  AND status = 'complete'
  AND deleted_at IS NULL
```
Returns 0 → HTTP 409 (`{ "detail": "KB has no compiled documents" }`).

---

## Runtime Entities (in-memory / filesystem — not persisted)

### QueryRequest

The inbound HTTP payload.

| Field | Type | Required | Validation | Notes |
|-------|------|----------|------------|-------|
| `question` | str | ✅ | Non-empty after strip; max 8000 chars | Passed verbatim to sidecar |
| `save` | bool | No | — | Accepted; always treated as no-op in Phase 0 |

Pydantic model with validators. `question` length cap prevents runaway LLM context.

---

### QueryResponse

The outbound HTTP payload.

| Field | Type | Notes |
|-------|------|-------|
| `answer` | str | Non-empty; verbatim from sidecar |
| `citations` | list[Any] | Verbatim from sidecar. Phase 0: `[]` (sidecar does not yet return structured citations) |
| `tokens_used` | int | From sidecar. Phase 0: `0` (sidecar does not yet return token counts) |

The `citations` field is typed `list[Any]` intentionally — the sidecar's citation schema is not
yet defined. When the sidecar begins returning structured citations, they pass through unchanged.

---

### WikiScratchDirectory

A per-request temporary directory on the local filesystem.

| Attribute | Value |
|-----------|-------|
| Path | `{SCRATCH_DIR_ROOT}/{request_id}/kbs/` |
| Contents | `{slug}/wiki/**` — full wiki tree downloaded from Azurite |
| Lifecycle | Created at start of request; deleted in `finally` block |
| Failure | `shutil.rmtree(path, ignore_errors=True)` ensures cleanup even on partial creation |

`request_id` = `uuid.uuid4()` (generated per request for uniqueness and debuggability).

**Directory layout after sync**:
```text
{SCRATCH_DIR_ROOT}/{request_id}/kbs/
└── {kb_slug}/
    └── wiki/
        ├── index.md
        ├── summaries/
        ├── concepts/
        ├── entities/
        ├── sources/
        │   ├── {doc-slug}.md
        │   ├── {doc-slug}.json
        │   └── images/
        └── explorations/
```

---

### OpenKBSidecar

A per-request subprocess instance of the OpenKB FastAPI server.

| Attribute | Value |
|-----------|-------|
| Command | `openkb serve --host 127.0.0.1 --port {port}` |
| Port | Dynamically allocated (socket bind-to-0) |
| Env | `OPENKB_STORAGE_BACKEND=local`, `OPENKB_BASE_DIR={scratch_dir}`, `LLM_API_KEY=...` |
| Readiness | Poll `GET /openapi.json` until HTTP 200 (timeout: `SIDECAR_STARTUP_TIMEOUT`) |
| Lifecycle | Spawned after wiki sync; torn down after query response (in `finally` block) |
| Isolation | Bound to `127.0.0.1` only; unique port; unique scratch dir |

**Sidecar scope rule**: one sidecar per request; never shared across concurrent requests or KBs.

---

## State Transitions

```
HTTP Request received
        │
        ▼
[1] Validate kb_id (UUID parse) ──fail──► 422
        │
        ▼
[2] DB pre-flight: KB exists? ──no──► 404
        │
        ▼
[3] DB pre-flight: complete docs? ──no──► 409
        │
        ▼
[4] Create scratch dir
        │
        ▼
[5] Sync wiki tree from Azurite ──fail──► 503 (cleanup scratch)
        │
        ▼
[6] Spawn sidecar, wait ready ──fail──► 502/503 (cleanup)
        │
        ▼
[7] POST /kb/init to sidecar ──fail──► 502 (cleanup)
        │
        ▼
[8] POST /kb/query to sidecar ──timeout──► 504 (cleanup)
        │        └──fail──► 502 (cleanup)
        ▼
[9] Build QueryResponse ──► HTTP 200
        │
        ▼ (finally)
[10] Terminate sidecar + rm scratch dir
```
