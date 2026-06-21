# Data Model: Phase 0 Postgres Schema

**Branch**: `002-phase0-postgres-schema`
**Date**: 2026-06-21
**Source**: `specs/001-phase0-postgres-schema/spec.md` FR-001 through FR-006, FR-014
**Authority**: `research/02-data-model.md` (upstream design document)

---

## Scope

Three tables only. All other tables listed in `research/02-data-model.md` (`organizations`, `users`, `kb_access`, `api_tokens`, `audit_log`, `usage_ledger`, `sso_config`, `chat_sessions`, `chat_messages`, `wiki_page_documents`, `collections`, `org_members`) are **out of scope for Phase 0** (FR-015).

---

## Entity Relationship Diagram

```
knowledge_bases
    │  id (PK)
    │  slug (UNIQUE)
    │
    ├──< documents
    │       id (PK)
    │       kb_id (FK → knowledge_bases.id) [INDEXED]
    │
    └──< wiki_pages
            id (PK)
            kb_id (FK → knowledge_bases.id) [INDEXED]
            UNIQUE (kb_id, slug)
```

All three tables share:
- UUID primary key with server-default `gen_random_uuid()`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `deleted_at TIMESTAMPTZ NULL` (soft-delete; no default)

---

## Table: `knowledge_bases`

The root container for a compilation project.

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | `UUID` | NOT NULL | `gen_random_uuid()` | PRIMARY KEY | Auto-generated server-side |
| `name` | `TEXT` | NOT NULL | — | — | Human-readable display name |
| `slug` | `TEXT` | NOT NULL | — | UNIQUE | URL-safe identifier; enforced at DB level (FR-004) |
| `description` | `TEXT` | NULL | — | — | Optional long-form description |
| `storage_container_path` | `TEXT` | NULL | — | — | e.g. `kb-{id}/` prefix in Blob Storage |
| `git_versioning_enabled` | `BOOLEAN` | NOT NULL | `TRUE` | — | Whether wiki changes are Git-versioned |
| `compilation_config` | `JSONB` | NULL | — | — | `{language, pageindex_threshold, entity_types, extra_headers}` — mirrors `config.yaml`; application validates shape |
| `status` | `TEXT` | NOT NULL | — | — | `active` \| `archived` — TEXT, not ENUM; application validates values |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `NOW()` | — | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `NOW()` | — | Application responsible for updating on writes |
| `deleted_at` | `TIMESTAMPTZ` | NULL | — | — | Soft-delete timestamp; NULL means not deleted |

**Indexes**:
- PRIMARY KEY on `id` (implicit B-tree)
- UNIQUE index on `slug` (FR-004)

**Phase 1 additions (additive migrations — not created here)**:
- `org_id UUID REFERENCES organizations(id)` — nullable initially, backfilled in migration (FR-014)
- `created_by UUID REFERENCES users(id)` — nullable initially

**SQLAlchemy Table definition sketch**:
```python
knowledge_bases = Table(
    "knowledge_bases",
    metadata,
    Column("id", UUID, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", Text, nullable=False),
    Column("slug", Text, nullable=False, unique=True),
    Column("description", Text, nullable=True),
    Column("storage_container_path", Text, nullable=True),
    Column("git_versioning_enabled", Boolean, nullable=False, server_default=text("TRUE")),
    Column("compilation_config", JSONB, nullable=True),
    Column("status", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")),
    Column("deleted_at", TIMESTAMP(timezone=True), nullable=True),
)
```

---

## Table: `documents`

A source artefact ingested into a `KnowledgeBase`.

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | `UUID` | NOT NULL | `gen_random_uuid()` | PRIMARY KEY | |
| `kb_id` | `UUID` | NOT NULL | — | FK → `knowledge_bases.id` | Indexed (FR-006) |
| `source_type` | `TEXT` | NOT NULL | — | — | `pdf`, `docx`, `pptx`, `xlsx`, `html`, `md`, `csv`, `url`, `text` |
| `source_uri` | `TEXT` | NULL | — | — | Blob path or original URL |
| `original_filename` | `TEXT` | NULL | — | — | Display name for the source file |
| `status` | `TEXT` | NOT NULL | — | — | `pending` \| `compiling` \| `complete` \| `failed` — TEXT; application validates |
| `failure_reason` | `TEXT` | NULL | — | — | Error message if `status = failed` |
| `pageindex_used` | `BOOLEAN` | NULL | — | — | `TRUE` if routed via PageIndex long-doc path |
| `token_cost` | `INTEGER` | NULL | — | — | LLM tokens consumed compiling this document |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `NOW()` | — | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `NOW()` | — | |
| `deleted_at` | `TIMESTAMPTZ` | NULL | — | — | Soft-delete |

**Indexes**:
- PRIMARY KEY on `id`
- B-tree index on `kb_id` (FR-006)

**Foreign key behaviour**: `kb_id` references `knowledge_bases.id` with `ON DELETE RESTRICT` (default) — a `knowledge_bases` row cannot be hard-deleted while documents reference it. Soft-delete pattern means hard deletes are not expected.

**Phase 1 additions (additive migrations — not created here)**:
- `added_by UUID REFERENCES users(id)` — nullable initially (FR-014)
- `collection_id UUID REFERENCES collections(id)` — nullable

**SQLAlchemy Table definition sketch**:
```python
documents = Table(
    "documents",
    metadata,
    Column("id", UUID, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("kb_id", UUID, ForeignKey("knowledge_bases.id"), nullable=False, index=True),
    Column("source_type", Text, nullable=False),
    Column("source_uri", Text, nullable=True),
    Column("original_filename", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("failure_reason", Text, nullable=True),
    Column("pageindex_used", Boolean, nullable=True),
    Column("token_cost", Integer, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")),
    Column("deleted_at", TIMESTAMP(timezone=True), nullable=True),
)
```

---

## Table: `wiki_pages`

A compiled output page generated by the OpenKB engine.

| Column | Type | Nullable | Default | Constraints | Notes |
|--------|------|----------|---------|-------------|-------|
| `id` | `UUID` | NOT NULL | `gen_random_uuid()` | PRIMARY KEY | |
| `kb_id` | `UUID` | NOT NULL | — | FK → `knowledge_bases.id` | Indexed (FR-006) |
| `page_type` | `TEXT` | NOT NULL | — | — | `summary`, `concept`, `entity`, `index`, `exploration` |
| `slug` | `TEXT` | NOT NULL | — | UNIQUE within `kb_id` | Matches markdown filename / wikilink target |
| `blob_path` | `TEXT` | NULL | — | — | Path to rendered markdown in Blob Storage |
| `entity_type` | `TEXT` | NULL | — | — | For entity pages: `person`, `organization`, `place`, `product`, `work`, `event`, `other` |
| `last_compiled_at` | `TIMESTAMPTZ` | NULL | — | — | When the page was last regenerated |
| `created_at` | `TIMESTAMPTZ` | NOT NULL | `NOW()` | — | |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL | `NOW()` | — | |
| `deleted_at` | `TIMESTAMPTZ` | NULL | — | — | Soft-delete |

**Indexes**:
- PRIMARY KEY on `id`
- B-tree index on `kb_id` (FR-006)
- UNIQUE index on `(kb_id, slug)` (FR-005)

**SQLAlchemy Table definition sketch**:
```python
wiki_pages = Table(
    "wiki_pages",
    metadata,
    Column("id", UUID, primary_key=True, server_default=text("gen_random_uuid()")),
    Column("kb_id", UUID, ForeignKey("knowledge_bases.id"), nullable=False, index=True),
    Column("page_type", Text, nullable=False),
    Column("slug", Text, nullable=False),
    Column("blob_path", Text, nullable=True),
    Column("entity_type", Text, nullable=True),
    Column("last_compiled_at", TIMESTAMP(timezone=True), nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()")),
    Column("deleted_at", TIMESTAMP(timezone=True), nullable=True),
    UniqueConstraint("kb_id", "slug", name="uq_wiki_pages_kb_id_slug"),
)
```

---

## Migration Plan

### Migration 0001: `0001_phase0_initial_schema`

**Creates**: `knowledge_bases`, `documents`, `wiki_pages` in dependency order.

**Operations**:
1. `CREATE TABLE knowledge_bases (...)` with all columns, PK, and UNIQUE(slug)
2. `CREATE TABLE documents (...)` with FK → `knowledge_bases.id`, PK, and index on `kb_id`
3. `CREATE TABLE wiki_pages (...)` with FK → `knowledge_bases.id`, PK, index on `kb_id`, and UNIQUE(kb_id, slug)

**Rollback (`downgrade`)**:
1. `DROP TABLE wiki_pages`
2. `DROP TABLE documents`
3. `DROP TABLE knowledge_bases`

**Idempotency**: Alembic's `alembic_version` table prevents re-applying. Running `alembic upgrade head` on an already-migrated database is a no-op (User Story 1, acceptance scenario 2).

### Stub Migration for Forward-Compatibility Test (SC-006)

A test-only migration (`0002_stub_phase1_add_org_id_added_by`) can be authored in `tests/db/` to verify SC-006. It adds:
```sql
ALTER TABLE knowledge_bases ADD COLUMN org_id UUID NULL;
ALTER TABLE documents ADD COLUMN added_by UUID NULL;
```
This migration must apply without errors against a Phase 0 database with seed data present.

---

## Validation Rules (Application Layer)

The following constraints are enforced by application code, not the database:

| Table | Column | Allowed values | Validation location |
|-------|--------|---------------|-------------------|
| `knowledge_bases` | `status` | `active`, `archived` | Service layer before INSERT/UPDATE |
| `documents` | `status` | `pending`, `compiling`, `complete`, `failed` | `compiler-worker` state machine |
| `knowledge_bases` | `compilation_config` | `{language: str, pageindex_threshold: float, entity_types: list[str], extra_headers: dict}` | Pydantic schema in control-plane API |
| `wiki_pages` | `page_type` | `summary`, `concept`, `entity`, `index`, `exploration` | `compiler-worker` output writer |
| `wiki_pages` | `entity_type` | `person`, `organization`, `place`, `product`, `work`, `event`, `other` or NULL | `compiler-worker` output writer |

---

## State Transitions

### `documents.status`

```
[INSERT]  →  pending
pending   →  compiling   (compiler-worker picks up job)
compiling →  complete    (compilation succeeded)
compiling →  failed      (compilation errored; failure_reason set)
failed    →  pending     (retry — requeued by control-plane API)
```

### `knowledge_bases.status`

```
[INSERT]  →  active
active    →  archived    (user archives KB via control-plane API)
archived  →  active      (user restores KB)
```
