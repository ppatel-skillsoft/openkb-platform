# Quickstart: Phase 0 Chat Session Assembly

**Feature**: Multi-turn chat sessions on `generator-api` | **Date**: 2026-06-21

This guide walks through verifying the Phase 0 chat feature end-to-end: from a clean Docker
Compose stack to a two-turn conversation that demonstrably uses context from the first turn.

---

## Prerequisites

- Docker and Docker Compose installed
- The Phase 0 stack running (postgres, azurite, redis, generator-api)
- A knowledge base with at least one `status = 'complete'` document in the database
- `curl` and `jq` available in your shell

> **Note**: Steps 1–3 are setup from prior specs (001 schema, 002 compiler-worker, 003
> generator-api). If you have an existing Phase 0 stack, skip to Step 4.

---

## Step 1: Start the Stack

```bash
docker compose up -d
```

Wait for all services to be healthy. Verify generator-api is reachable:

```bash
curl -s http://localhost:8001/health | jq .
# Expected: { "status": "ok", "postgres": "ok", "azurite": "ok" }
```

---

## Step 2: Apply Migrations

If this is the first time running with the chat tables migration:

```bash
docker compose exec generator-api alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade 001_phase0_schema -> 002_chat_tables, chat tables
```

Verify the tables exist:

```bash
docker compose exec postgres psql -U openkb -d openkb -c "\dt"
# Should list: knowledge_bases, documents, wiki_pages, chat_sessions, chat_messages
```

---

## Step 3: Find a Queryable KB ID

```bash
KB_ID=$(docker compose exec postgres psql -U openkb -d openkb -At \
  -c "SELECT id FROM knowledge_bases WHERE status='active' LIMIT 1;")
echo "KB_ID=$KB_ID"
```

Verify it has compiled content:

```bash
docker compose exec postgres psql -U openkb -d openkb -At \
  -c "SELECT COUNT(*) FROM documents WHERE kb_id='$KB_ID' AND status='complete';"
# Should be > 0
```

---

## Step 4: Create a Chat Session

```bash
SESSION=$(curl -s -X POST \
  "http://localhost:8001/kbs/${KB_ID}/chat/sessions" \
  -H "Content-Type: application/json" \
  -d '{}')

echo "$SESSION" | jq .
SESSION_ID=$(echo "$SESSION" | jq -r '.session_id')
echo "SESSION_ID=$SESSION_ID"
```

**Expected response (`201 Created`)**:
```json
{
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "kb_id": "<your-kb-id>",
  "via": "web",
  "title": null,
  "created_at": "2026-06-21T15:00:00Z"
}
```

Note that `title` is `null` — it will be set when the first message is sent.

---

## Step 5: Send the First Message

```bash
TURN1=$(curl -s -X POST \
  "http://localhost:8001/kbs/${KB_ID}/chat/sessions/${SESSION_ID}/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "What is PageIndex?"}')

echo "$TURN1" | jq .
```

**Expected response (`200 OK`)**:
```json
{
  "message_id": "...",
  "session_id": "<SESSION_ID>",
  "role": "assistant",
  "content": "PageIndex is a document indexing technique that ...",
  "citations": [...],
  "token_cost": 350,
  "created_at": "2026-06-21T15:01:00Z",
  "session_title": "What is PageIndex?"
}
```

**What to check**:
- `role` is `"assistant"` ✅
- `content` is non-empty and grounded in the KB content ✅
- `session_title` is no longer null (auto-generated from first message) ✅
- `citations` may be empty array for simple questions — that is valid ✅

---

## Step 6: Send a Follow-Up Message (Multi-Turn Validation)

This is the Phase 0 exit criterion: the second answer must demonstrably use context from the
first turn — without the caller repeating what was discussed.

```bash
TURN2=$(curl -s -X POST \
  "http://localhost:8001/kbs/${KB_ID}/chat/sessions/${SESSION_ID}/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "How is it used in this document?"}')

echo "$TURN2" | jq .answer
```

**What to check**:
- The answer references `PageIndex` (introduced in Turn 1) **without** the caller repeating
  what it is — confirming history was injected into the upstream query ✅
- If the answer says something like "I'm not sure what 'it' refers to", history injection
  has failed — re-check `CHAT_HISTORY_WINDOW` and the assembly logic in `chat_session_svc.py`

---

## Step 7: Retrieve Message History

```bash
curl -s "http://localhost:8001/kbs/${KB_ID}/chat/sessions/${SESSION_ID}/messages" | jq .
```

**Expected**: 4 messages in chronological order:
1. `role: "user"`, `content: "What is PageIndex?"`
2. `role: "assistant"`, `content: "<answer from Turn 1>"`
3. `role: "user"`, `content: "How is it used in this document?"`
4. `role: "assistant"`, `content: "<answer from Turn 2>"`

---

## Step 8: List Sessions

```bash
curl -s "http://localhost:8001/kbs/${KB_ID}/chat/sessions" | jq .
```

**Expected**: Session list with at least the session you created, now showing a non-null title.

---

## Error Path Verification

### 400 — Empty message content

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://localhost:8001/kbs/${KB_ID}/chat/sessions/${SESSION_ID}/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "   "}'
# Expected: 400
```

### 404 — Session not found

```bash
curl -s -o /dev/null -w "%{http_code}" \
  "http://localhost:8001/kbs/${KB_ID}/chat/sessions/00000000-0000-0000-0000-000000000000/messages"
# Expected: 404
```

### 404 — KB not found

```bash
curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://localhost:8001/kbs/00000000-0000-0000-0000-000000000000/chat/sessions" \
  -H "Content-Type: application/json" -d '{}'
# Expected: 404
```

### Cross-KB session validation

```bash
# Create a second KB (or use a known different KB_ID), then try to send
# a message to SESSION_ID from KB 1 using KB 2's id in the URL path:
curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://localhost:8001/kbs/${OTHER_KB_ID}/chat/sessions/${SESSION_ID}/messages" \
  -H "Content-Type: application/json" \
  -d '{"content": "test"}'
# Expected: 404
```

---

## History Window Validation (SC-005)

To verify the window limit is enforced, set a small window and create more turns than the limit:

```bash
# Requires restarting generator-api with CHAT_HISTORY_WINDOW=2
docker compose stop generator-api
CHAT_HISTORY_WINDOW=2 docker compose up -d generator-api

# Create a new session and send 4 messages
SESSION2=$(curl -s -X POST "http://localhost:8001/kbs/${KB_ID}/chat/sessions" \
  -H "Content-Type: application/json" -d '{}' | jq -r '.session_id')

for i in 1 2 3 4; do
  curl -s -X POST \
    "http://localhost:8001/kbs/${KB_ID}/chat/sessions/${SESSION2}/messages" \
    -H "Content-Type: application/json" \
    -d "{\"content\": \"Turn $i question about the KB.\"}" > /dev/null
done

# Send turn 5 — its assembled context should only include turns 3 and 4 (window=2)
# Check the service logs to see the assembled question string
docker compose logs generator-api --tail=20
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `404` on session create | KB not in `knowledge_bases` or `status ≠ 'active'` | Insert or activate a KB row |
| `409` on message send | No `complete` documents for KB | Run compiler-worker for the KB |
| `502`/`504` on message send | Sidecar failing or timing out | Check sidecar logs; increase `SIDECAR_TIMEOUT` |
| Second turn answer doesn't reference first turn | History not assembled correctly | Check `CHAT_HISTORY_WINDOW > 0`; check `chat_session_svc.py` assembly logic |
| Migration fails with FK error | spec 001 migration hasn't been applied yet | Run `alembic upgrade 001_phase0_schema` first |
