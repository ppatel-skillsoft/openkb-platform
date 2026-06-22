# Data Model: Phase 0 Chat Session Assembly

**Spec**: [spec.md](./spec.md) | **Research**: [research.md](./research.md) | **Date**: 2026-06-21

This document describes the two new database tables introduced by this feature and how they relate
to the existing Phase 0 schema (spec 001). These tables are created by Alembic migration
`002_chat_tables` which declares `down_revision` pointing to spec 001's `001_phase0_schema`.

---

## Inherited Tables (spec 001 — do not modify)

```
knowledge_bases (id UUID PK, name, slug, description, storage_container_path,
                 git_versioning_enabled, compilation_config JSONB, status,
                 created_at, updated_at, deleted_at)

documents       (id UUID PK, kb_id UUID FK→knowledge_bases, source_type, source_uri,
                 original_filename, status, failure_reason, pageindex_used,
                 token_cost, created_at, updated_at, deleted_at)

wiki_pages      (id UUID PK, kb_id UUID FK→knowledge_bases, page_type, slug,
                 blob_path, entity_type, last_compiled_at,
                 created_at, updated_at, deleted_at)
```

---

## New Tables (this feature — migration 002_chat_tables)

### `chat_sessions`

Represents a single ongoing multi-turn conversation scoped to a knowledge base.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `UUID` | PK, NOT NULL | Python `uuid.uuid4()` at INSERT; `server_default=gen_random_uuid()` fallback |
| `kb_id` | `UUID` | NOT NULL, FK→`knowledge_bases.id` ON DELETE CASCADE | Scopes the session to a KB |
| `via` | `TEXT` | NOT NULL, DEFAULT `'web'` | Client type (`'web'` in Phase 0; `'mcp'` in Phase 2) |
| `title` | `TEXT` | NULLABLE | NULL until first message is sent; auto-generated (60 char truncation) |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | Session creation time |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | Updated on every new message |
| `deleted_at` | `TIMESTAMPTZ` | NULLABLE | Soft-delete support for Phase 1; no delete endpoint in Phase 0 |

**Indexes**:
- PK index on `id` (implicit)
- Index on `kb_id` — for `GET /kbs/{kb_id}/chat/sessions` list query
- Index on `(kb_id, created_at DESC)` — for ordered session listing

**Constraints**:
- `kb_id` FK with ON DELETE CASCADE: if the KB is hard-deleted (not typical in Phase 0), sessions
  are cascaded. In practice, soft-delete via `knowledge_bases.deleted_at` is used.

**No `user_id` FK in Phase 0** — no users table exists yet. This column will be added as a
nullable FK in a Phase 1 migration when `users` is introduced.

---

### `chat_messages`

Represents a single turn in a conversation. Immutable once written.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | `UUID` | PK, NOT NULL | Python `uuid.uuid4()` at INSERT |
| `session_id` | `UUID` | NOT NULL, FK→`chat_sessions.id` ON DELETE CASCADE | Parent session |
| `role` | `TEXT` | NOT NULL | `'user'` or `'assistant'` — application-enforced enum |
| `content` | `TEXT` | NOT NULL | Message text; user input or assistant answer |
| `citations` | `JSONB` | NULLABLE | Citation objects from sidecar, stored verbatim; NULL for user messages |
| `token_cost` | `INTEGER` | NULLABLE | Tokens used for this response; NULL for user messages |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | Immutable write timestamp; used for history ordering |

**No `updated_at` or `deleted_at`**: Messages are immutable once written. There is no message
edit or delete operation in Phase 0 (or planned for Phase 1).

**Indexes**:
- PK index on `id` (implicit)
- Index on `session_id` — for history queries
- Index on `(session_id, created_at ASC)` — primary history ordering index
- Index on `(session_id, created_at DESC)` — for window query (fetch last N messages)

---

## Entity Relationships

```
knowledge_bases ──< chat_sessions ──< chat_messages
    (spec 001)         (spec 005)          (spec 005)

knowledge_bases.id  ←  chat_sessions.kb_id
chat_sessions.id    ←  chat_messages.session_id
```

**Cardinalities**:
- One KB → many sessions (`0..*`)
- One session → many messages (`0..*`; typically pairs of user+assistant)

---

## State Transitions

### `chat_sessions` lifecycle (Phase 0)

```
[created — title=NULL]
    │
    │  (first message sent)
    ▼
[active — title=auto-generated]
    │
    │  (further messages sent; updated_at refreshed each time)
    ▼
[active — title set]
    │
    │  (soft-delete — Phase 1 only; no Phase 0 endpoint)
    ▼
[soft-deleted — deleted_at set]
```

### `chat_messages` lifecycle

Messages are **write-once / immutable**. No state transitions. The only operation is INSERT.

---

## Validation Rules

| Entity | Field | Validation | Layer |
|---|---|---|---|
| `chat_sessions` | `kb_id` | Must reference an existing, non-soft-deleted `knowledge_bases.id` | Application (404 if miss) |
| `chat_messages` | `content` | Must be non-empty / non-whitespace-only | Application (400 before DB write) |
| `chat_messages` | `role` | Must be `'user'` or `'assistant'` | Application (Pydantic enum) |
| `chat_messages` | `session_id` | `(session_id, kb_id)` must match the URL path `kb_id` | Application (404 validation query) |
| `chat_sessions` | `deleted_at` | Any query serving API requests filters `WHERE deleted_at IS NULL` | Application (SQL WHERE clause) |

---

## Migration DDL (Alembic `002_chat_tables.py`)

```python
# upgrade()
op.create_table(
    'chat_sessions',
    sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
    sa.Column('kb_id', pg.UUID(as_uuid=True),
              sa.ForeignKey('knowledge_bases.id', ondelete='CASCADE'), nullable=False),
    sa.Column('via', sa.Text(), nullable=False, server_default='web'),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
              server_default=sa.text('now()')),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
              server_default=sa.text('now()')),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
)
op.create_index('ix_chat_sessions_kb_id', 'chat_sessions', ['kb_id'])
op.create_index('ix_chat_sessions_kb_id_created_at', 'chat_sessions',
                ['kb_id', sa.text('created_at DESC')])

op.create_table(
    'chat_messages',
    sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
    sa.Column('session_id', pg.UUID(as_uuid=True),
              sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', pg.JSONB(), nullable=True),
    sa.Column('token_cost', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
              server_default=sa.text('now()')),
)
op.create_index('ix_chat_messages_session_id', 'chat_messages', ['session_id'])
op.create_index('ix_chat_messages_session_id_created_at_asc', 'chat_messages',
                ['session_id', sa.text('created_at ASC')])
op.create_index('ix_chat_messages_session_id_created_at_desc', 'chat_messages',
                ['session_id', sa.text('created_at DESC')])

# downgrade()
op.drop_table('chat_messages')
op.drop_table('chat_sessions')
```

---

## Post-Phase 1 Constitution Check Re-evaluation

> Constitution is an unfilled template — no operative gates to re-evaluate.
>
> **Engineering check**: The data model satisfies all FR requirements:
> - FR-008 ✅ Sessions keyed by `(kb_id, session_id)` — no user_id
> - FR-014 ✅ Postgres only; no Redis
> - FR-015 ✅ New migration builds on spec 001 schema
> - Forward compatibility ✅ `user_id` can be added as nullable FK in Phase 1 migration
