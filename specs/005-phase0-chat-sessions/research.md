# Research: Phase 0 Chat Session Assembly

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-06-21

This document resolves all NEEDS CLARIFICATION items from the Technical Context and captures
the key design decisions made during Phase 0 planning.

---

## 1. Context Assembly Format for the Upstream Query Sidecar

**Unknown**: What format should assembled conversation history take when passed to the existing
`POST /kbs/{kb_id}/query` endpoint (via the sidecar)? The sidecar accepts a free-text `question`
field. Does it understand conversation history natively?

**Research findings**:
- The `generator-api` query sidecar (spec 003) accepts `{ "question": string }` and treats the
  entire string as the query context. It does not have a native multi-turn conversation format.
- The existing OpenKB CLI chat (`openkb/agent/chat.py`) passes the full `RunResult.to_input_list()`
  agent SDK history to the agents framework across turns — but that is an in-process mechanism
  not available over HTTP.
- The spec explicitly states (Assumption 2): *"A simple conversational history prefix format —
  such as prepending prior turns as labelled text before the new question — is sufficient for
  Phase 0 to demonstrate multi-turn coherence."*

**Decision: Labelled text prefix format**

```
Previous conversation:
User: {turn_1_user_content}
Assistant: {turn_1_assistant_content}
User: {turn_2_user_content}
Assistant: {turn_2_assistant_content}

User: {current_question}
```

- The assembled string is placed entirely in the `question` field of the sidecar request body.
- A blank line separates the history block from the current question to improve LLM parsing.
- Role labels `User:` and `Assistant:` are chosen for clarity over `Human:`/`AI:` — consistent
  with most base LLM instruction-following defaults.
- If there is no prior history (first turn), the `question` field is the bare user message with
  no prefix — backwards compatible with existing sidecar callers.

**Alternatives considered**:
- **System prompt injection**: Would require a sidecar API change (adding a `system_prompt` field).
  Out of scope for Phase 0 — the sidecar is treated as a black box.
- **Separate `context` field**: Same problem — requires a sidecar API change.
- **Store history in Redis**: Explicitly out of scope per spec (FR-014, Assumption 5).

---

## 2. History Window Enforcement

**Unknown**: How should the N-turn window be implemented? Is N measured in "turns" (user+assistant
pairs) or "messages" (individual rows)?

**Decision: N = number of message rows (not turn pairs), configurable via `CHAT_HISTORY_WINDOW`**

- **Why rows, not pairs**: Simpler DB query (`LIMIT N`), no special pairing logic needed.
  The assembled prefix naturally interleaves user and assistant messages in chronological order.
  If a session has orphaned user messages (e.g., sidecar error before assistant response was
  persisted), the window still works correctly.
- **Default**: `CHAT_HISTORY_WINDOW=20` (10 user + 10 assistant = 10 turn-pairs). This provides
  ample context for Phase 0 validation while staying comfortably within LLM context limits.
  Spec default of "10 turns" ≈ 20 rows.
- **Query pattern**:
  ```sql
  SELECT role, content FROM chat_messages
  WHERE session_id = :session_id
  ORDER BY created_at DESC
  LIMIT :window
  ```
  Then reverse the result set in Python before formatting the history prefix (to restore
  chronological order for the assembled string).
- **Zero or negative window**: Treated as invalid; service falls back to the default (20) and
  logs a warning. Spec edge case requirement satisfied.

**Alternatives considered**:
- **Token counting**: Accurate but requires embedding the LLM tokenizer in the service layer.
  Overkill for Phase 0; deferred to Phase 1 prompt engineering.
- **Time-based window**: Not semantically meaningful for conversation context.

---

## 3. Alembic Migration Ordering

**Unknown**: How should the two new chat tables be introduced as Alembic migrations, given they
build on spec 001's existing `001_phase0_schema` migration?

**Decision: Single new revision `002_chat_tables.py` with FK dependency on `knowledge_bases`**

- Migration `002` has `down_revision = '001_phase0_schema'` (or the actual rev ID of the spec 001
  migration after it is applied).
- Both `chat_sessions` and `chat_messages` are created in the same revision file since they are
  always deployed together and `chat_messages.session_id` depends on `chat_sessions`.
- The `upgrade()` function creates `chat_sessions` first, then `chat_messages` (FK ordering).
- The `downgrade()` function drops `chat_messages` first, then `chat_sessions`.
- **SC-006 coverage**: Migration applies cleanly on top of spec 001 schema — verified by running
  `alembic upgrade head` on a database that has only `001_phase0_schema` applied.

**Alternatives considered**:
- Two separate revision files (one per table): Unnecessary complexity; these tables are always
  deployed and rolled back together.
- DDL-only (no Alembic): Would break the incremental migration history required by spec 001 FR-007.

---

## 4. UUID Generation: Python vs Postgres

**Unknown**: Should UUIDs for `chat_sessions.id` and `chat_messages.id` be generated in Python
(at INSERT time, before the DB call) or by Postgres (`gen_random_uuid()` default)?

**Decision: Python-generated UUIDs (`uuid.uuid4()` in the service layer)**

- **Rationale**: Python-generated UUIDs allow the session/message ID to be known before the
  `INSERT` is issued, enabling the service to return the ID in the response body without an
  additional `RETURNING id` round-trip (though SQLAlchemy Core 2.x supports `RETURNING` anyway).
  More importantly, it is consistent with the pattern established by spec 001 (all PKs are
  `UUID` with `server_default=text("gen_random_uuid()")` as a fallback, but the application
  generates them explicitly).
- Postgres `gen_random_uuid()` is retained as a `server_default` in the DDL for safety (direct
  SQL inserts without the Python layer will still get a valid UUID).

**Alternatives considered**:
- DB-only UUIDs: Simpler DDL but requires an extra round-trip or `RETURNING` clause on every
  INSERT to retrieve the generated ID before constructing the API response.

---

## 5. Error Handling When the Sidecar Fails During a Chat Turn

**Unknown**: If the sidecar call fails (timeout, 5xx, network error) after the user message
has already been received, should the user message be persisted to `chat_messages`?

**Decision: Do not persist any message from a failed turn; propagate error to caller**

- **Rationale**: A half-persisted turn (user message with no assistant response) would corrupt
  the assembled history on the next turn — the window query would include a dangling user message
  with no corresponding assistant reply, producing a malformed context prefix.
- **Implementation**: The service layer uses a single DB transaction per turn:
  1. Write user message to `chat_messages` (within transaction, not yet committed).
  2. Call the sidecar (outside the transaction — network I/O cannot be inside a DB tx).
  3. If sidecar succeeds: write assistant message and commit the transaction.
  4. If sidecar fails: roll back the transaction (user message is not persisted).
  5. Return the appropriate error (502/503/504) to the caller.
- This preserves the invariant: every user message in `chat_messages` has a corresponding
  assistant message immediately following it.
- **Edge case**: If the commit after step 3 fails, the user message is also not persisted.
  This is acceptable for Phase 0; idempotent retry is a Phase 1 concern.

**Spec edge case coverage**: "The chat endpoint should propagate a meaningful error to the caller
rather than silently failing or persisting a partial message." ✅

---

## 6. Session Ownership Validation (`session_id` belongs to `kb_id`)

**Unknown**: How should the service validate that a `session_id` belongs to the `kb_id` specified
in the URL path? Single query or join?

**Decision: Single `SELECT` with compound WHERE on both `session_id` and `kb_id`**

```sql
SELECT id, kb_id FROM chat_sessions
WHERE id = :session_id AND kb_id = :kb_id AND deleted_at IS NULL
```

- If no row is returned: respond with `404 Not Found` (covers both "session doesn't exist" and
  "session belongs to different KB" cases — unified into a single 404 per spec FR-011).
- This is a single indexed lookup (PK on `id`, FK index on `kb_id`); no join required.
- The spec allows 404 or 403 for the cross-KB case; 404 is chosen to avoid leaking the existence
  of sessions that belong to other KBs.

---

## 7. Auto-Title Generation

**Unknown**: When exactly is the session title set — at session creation or after the first
message?

**Decision: Set title after the first user message is persisted (not at session creation)**

- At `POST /kbs/{kb_id}/chat/sessions`, the title is `NULL` — the session exists with no title.
- When the first message is sent via `POST /kbs/{kb_id}/chat/sessions/{id}/messages`:
  1. Check if `chat_sessions.title IS NULL` (i.e., this is the first message).
  2. If so, truncate the message content to 60 characters (with `…` if truncated) and UPDATE
     `chat_sessions.title`.
  3. This update is included in the same DB transaction as the message persist.
- **Why not at session creation**: The session creation request has no message content.
- **Truncation implementation**: `_title_from()` in `openkb/agent/chat_session.py` already
  implements this exact logic. Reuse that function in the new service layer.

---

## 8. `via` Field Default and Extensibility

**Unknown**: Is the `via` field on `chat_sessions` just `'web'` for all Phase 0 sessions?
Does it need to be settable by the caller?

**Decision: Hard-coded default `'web'` in Phase 0; not settable via API**

- The session creation endpoint (`POST /kbs/{kb_id}/chat/sessions`) does not accept a `via`
  parameter in Phase 0.
- `via` is stored as `'web'` for all sessions, providing a clean audit trail when `'mcp'`
  sessions are added in Phase 2.
- The DB column is `TEXT NOT NULL DEFAULT 'web'`, so the application layer does not need to
  set it explicitly.

---

## Summary of All Resolved Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Context assembly format | Labelled text prefix (`User: … \nAssistant: …`) in `question` field |
| 2 | History window unit | Rows (not pairs); `CHAT_HISTORY_WINDOW=20`; fall back to default if ≤ 0 |
| 3 | Migration ordering | Single revision `002_chat_tables` with `down_revision` pointing to spec 001 |
| 4 | UUID generation | Python `uuid.uuid4()` with Postgres `gen_random_uuid()` as DDL server_default |
| 5 | Sidecar failure handling | Single DB transaction per turn; rollback on sidecar failure; no partial persist |
| 6 | KB ownership validation | Single `SELECT WHERE id = :session_id AND kb_id = :kb_id`; 404 on miss |
| 7 | Auto-title timing | Set on first message; reuse `_title_from()` truncation logic; same transaction |
| 8 | `via` field | Hard-coded `'web'`; not caller-settable in Phase 0 |
