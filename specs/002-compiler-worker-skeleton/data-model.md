# Data Model: Compiler Worker Skeleton (Phase 0)

**Feature**: `003-compiler-worker-skeleton`  
**Date**: 2026-06-21  
**Depends on**: `specs/001-phase0-postgres-schema/spec.md` (tables:
`knowledge_bases`, `documents`, `wiki_pages`)

---

## 1. Inherited Schema (Spec 001 — Read + Write)

The compiler-worker reads from and writes to the three tables defined in
spec 001. They are reproduced here with the columns that the worker
specifically touches highlighted.

### `knowledge_bases` (read-only by worker)

| Column | Type | Worker access |
|---|---|---|
| `id` | uuid PK | Filter by `kb_id` from job message |
| `name` | text | — |
| `slug` | text unique | — |
| `storage_container_path` | text | Derive blob container name (`kb-{id}`) |
| `compilation_config` | jsonb | Pass `model` + `language` to `/init` |
| `status` | text | Assert `active` before processing |
| `created_at`, `updated_at`, `deleted_at` | timestamptz | — |

**Worker query pattern**:
```sql
SELECT id, storage_container_path, compilation_config, status
FROM knowledge_bases
WHERE id = :kb_id AND deleted_at IS NULL;
```

---

### `documents` (read + write by worker)

| Column | Type | Worker writes |
|---|---|---|
| `id` | uuid PK | — |
| `kb_id` | uuid FK → knowledge_bases | — |
| `source_type` | text | — |
| `source_uri` | text | Download source blob path |
| `original_filename` | text | Filename for scratch dir `raw/` |
| **`status`** | text | `pending` → `compiling` → `complete` \| `failed` |
| **`failure_reason`** | text nullable | Written on failure only |
| **`pageindex_used`** | boolean | Populated from sidecar status response |
| **`token_cost`** | integer nullable | Populated from sidecar status response |
| `created_at`, `updated_at` | timestamptz | `updated_at = now()` on each write |
| `deleted_at` | timestamptz nullable | — (worker never deletes) |

**Status lifecycle transitions performed by the worker**:

```
pending → compiling    (on job dequeue, before sidecar spawn)
compiling → complete   (on successful sidecar status: "complete")
compiling → failed     (on timeout, sidecar error, blob error, or DB error)
```

**Worker write patterns**:
```sql
-- Transition to compiling
UPDATE documents
SET status = 'compiling', updated_at = now()
WHERE id = :doc_id AND status = 'pending';

-- Record success
UPDATE documents
SET status = 'complete',
    token_cost = :token_cost,
    pageindex_used = :pageindex_used,
    updated_at = now()
WHERE id = :doc_id;

-- Record failure
UPDATE documents
SET status = 'failed',
    failure_reason = :reason,
    updated_at = now()
WHERE id = :doc_id;

-- Startup stale recovery (all compiling docs for this worker's KB scope)
UPDATE documents
SET status = 'failed',
    failure_reason = 'Worker restarted with job in progress — marked failed for safety',
    updated_at = now()
WHERE status = 'compiling' AND deleted_at IS NULL;
```

---

### `wiki_pages` (upsert by worker on success)

| Column | Type | Worker writes |
|---|---|---|
| `id` | uuid PK | Generated on insert |
| **`kb_id`** | uuid FK → knowledge_bases | From job message |
| **`page_type`** | text | From sidecar status response |
| **`slug`** | text | From sidecar status response (e.g. `summaries/foo`) |
| **`blob_path`** | text | Constructed: `kb-{id}/wiki/{slug}.md` |
| **`entity_type`** | text nullable | From sidecar status response (entity pages only) |
| **`last_compiled_at`** | timestamptz | Set to `now()` on upsert |
| `created_at`, `updated_at` | timestamptz | Managed by upsert |
| `deleted_at` | timestamptz nullable | — |

**Worker upsert pattern** (one call per page returned by sidecar):
```sql
INSERT INTO wiki_pages
    (id, kb_id, page_type, slug, blob_path, entity_type, last_compiled_at,
     created_at, updated_at)
VALUES
    (gen_random_uuid(), :kb_id, :page_type, :slug, :blob_path,
     :entity_type, now(), now(), now())
ON CONFLICT (kb_id, slug) DO UPDATE SET
    page_type        = EXCLUDED.page_type,
    blob_path        = EXCLUDED.blob_path,
    entity_type      = EXCLUDED.entity_type,
    last_compiled_at = EXCLUDED.last_compiled_at,
    updated_at       = EXCLUDED.updated_at;
```

---

## 2. In-Memory Models (not persisted)

These dataclasses live in `compiler_worker/` and are never written to a
database or queue directly.

### `CompilationJob`

Deserialised from the Redis queue message.

```python
@dataclass
class CompilationJob:
    job_id: str        # UUID; idempotency key
    kb_id: str         # UUID; FK → knowledge_bases.id
    document_id: str   # UUID; FK → documents.id
    blob_path: str     # e.g. "kb-<uuid>/raw/report.md"
    filename: str      # e.g. "report.md"
    enqueued_at: str   # ISO-8601 timestamp; for observability logging
```

### `SidecarPage`

Deserialised from `GET /status` response `pages` array.

```python
@dataclass
class SidecarPage:
    slug: str                    # e.g. "summaries/report"
    page_type: str               # "summary" | "concept" | "entity" | "index"
    entity_type: str | None      # e.g. "person"; null for non-entity pages
    file_path: str               # relative path in scratch wiki dir
                                 # e.g. "wiki/summaries/report.md"
```

### `SidecarStatus`

Full response from `GET /status`.

```python
@dataclass
class SidecarStatus:
    status: str                  # "idle" | "compiling" | "complete" | "failed"
    pages: list[SidecarPage]     # empty until status == "complete"
    token_cost: int | None       # total tokens billed; null until complete
    pageindex_used: bool | None  # true if long-doc path was taken; null until complete
    error: str | None            # human-readable; null on success
```

---

## 3. Configuration Model

All worker configuration is read from environment variables at startup.
If a required variable is missing, `WorkerConfig.__post_init__` raises
`ValueError` immediately (fail-fast principle).

```python
@dataclass
class WorkerConfig:
    # Postgres
    database_url: str           # DATABASE_URL — e.g. postgresql+asyncpg://...

    # Redis queue
    redis_url: str              # REDIS_URL — e.g. redis://localhost:6379/0
    queue_key: str              # QUEUE_KEY — default: "compiler:jobs"
    queue_poll_timeout: int     # QUEUE_POLL_TIMEOUT_S — default: 5

    # Blob Storage
    blob_connection_string: str # AZURE_STORAGE_CONNECTION_STRING

    # Sidecar
    sidecar_image: str          # SIDECAR_IMAGE — Docker image or binary path
    sidecar_startup_timeout: int # SIDECAR_STARTUP_TIMEOUT_S — default: 15
    sidecar_compile_timeout: int # SIDECAR_COMPILE_TIMEOUT_S — default: 300
    sidecar_poll_interval: float # SIDECAR_POLL_INTERVAL_S — default: 2.0

    # Phase 0 KB scope
    kb_id: str                  # KB_ID — single hardcoded KB UUID for Phase 0
```

---

## 4. Blob Storage Layout

See [contracts/blob-storage-paths.md](./contracts/blob-storage-paths.md) for
the full specification. Summary:

| Purpose | Container | Blob path |
|---|---|---|
| Source document input | `kb-{id}` | `raw/{filename}` |
| Compiled wiki page | `kb-{id}` | `wiki/{slug}.md` |

The `storage_container_path` column on `knowledge_bases` stores the
container name prefix (e.g. `kb-{id}`). The worker reads this value and
constructs all blob paths relative to it.

---

## 5. Page Type Vocabulary

Derived from `openkb/schema.py` `PAGE_CONTENT_DIRS` and `AGENTS_MD`:

| `page_type` value | Directory | `entity_type` |
|---|---|---|
| `summary` | `wiki/summaries/` | always null |
| `concept` | `wiki/concepts/` | always null |
| `entity` | `wiki/entities/` | required (e.g. `person`, `organization`) |
| `index` | `wiki/` | always null (for `index.md`) |

The `entity_type` vocabulary is governed by `openkb/config.py`
`DEFAULT_ENTITY_TYPES` and is extensible via `compilation_config.entity_types`
on the `knowledge_bases` row.
