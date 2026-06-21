# HTTP Contract: Phase 0 Chat Session Assembly

**Service**: `generator-api` (port 8001) | **Spec**: [spec.md](../spec.md) | **Date**: 2026-06-21

These four endpoints are added to the existing `generator-api` FastAPI application. They share the
same process, port (8001), and Docker Compose container as the existing `POST /kbs/{kb_id}/query`
endpoint defined in spec 003. No new service or container is required.

---

## Common Conventions

- **Content-Type**: All requests and responses use `application/json`
- **Path parameters**: `kb_id` and `session_id` are UUID strings (e.g., `"3fa85f64-..."`);
  non-UUID values return `422 Unprocessable Entity`
- **Error body**: All error responses use `{ "detail": "<human-readable message>" }`
- **Authentication**: None in Phase 0
- **Pagination**: None in Phase 0 (all results returned in a single response)
- **Soft-deleted sessions**: Never returned by any list or lookup endpoint
  (`WHERE deleted_at IS NULL` applied by default)

---

## Endpoint 1: Create Chat Session

### `POST /kbs/{kb_id}/chat/sessions`

Creates a new chat session scoped to the specified knowledge base.

**Path Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `kb_id` | UUID string | Yes | The knowledge base to associate the session with |

**Request Body** *(optional JSON body)*

```json
{}
```

No fields required in Phase 0. An empty body or no body is accepted. Future phases may add
`{ "via": "mcp" }` etc.

**Success Response — `201 Created`**

```json
{
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "kb_id":      "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "via":        "web",
  "title":      null,
  "created_at": "2026-06-21T15:00:00Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `session_id` | UUID string | Unique identifier for the new session |
| `kb_id` | UUID string | Echoes the path parameter |
| `via` | string | `"web"` (hard-coded in Phase 0) |
| `title` | string or null | `null` until the first message is sent |
| `created_at` | ISO 8601 UTC | Session creation timestamp |

**Error Responses**

| Status | When |
|---|---|
| `400 Bad Request` | `kb_id` is present but malformed (non-UUID format) |
| `404 Not Found` | `kb_id` does not exist in `knowledge_bases` |
| `422 Unprocessable Entity` | Path parameter fails Pydantic UUID validation |

---

## Endpoint 2: Send Message (Session-Assembly Loop)

### `POST /kbs/{kb_id}/chat/sessions/{session_id}/messages`

Sends a user message, assembles conversation history, calls the upstream query sidecar, persists
the exchange, and returns the assistant response.

This is the core endpoint. It performs the session-assembly loop described in research.md §1–§5.

**Path Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `kb_id` | UUID string | Yes | Must match the KB that owns the session |
| `session_id` | UUID string | Yes | The session to send the message to |

**Request Body**

```json
{
  "content": "What is PageIndex and how does it differ from standard RAG?"
}
```

| Field | Type | Required | Validation |
|---|---|---|---|
| `content` | string | Yes | Non-empty; non-whitespace-only; stripped before use |

**Success Response — `200 OK`**

```json
{
  "message_id":  "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "session_id":  "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "role":        "assistant",
  "content":     "PageIndex is a document indexing technique that ...",
  "citations":   [
    {
      "title":   "PageIndex Overview",
      "source":  "wiki/summary/pageindex-overview.md",
      "snippet": "PageIndex structures long documents into ..."
    }
  ],
  "token_cost":  412,
  "created_at":  "2026-06-21T15:01:00Z",
  "session_title": "What is PageIndex and how does it d…"
}
```

| Field | Type | Notes |
|---|---|---|
| `message_id` | UUID string | ID of the persisted assistant message |
| `session_id` | UUID string | Echoes the path parameter |
| `role` | string | Always `"assistant"` |
| `content` | string | The assistant's answer |
| `citations` | array | Citation objects from sidecar, passed through verbatim (may be empty array) |
| `token_cost` | integer or null | Tokens used by the sidecar for this response |
| `created_at` | ISO 8601 UTC | Timestamp of the assistant message row |
| `session_title` | string or null | The (possibly just-generated) session title; null if somehow not set |

**Processing sequence** (service layer):

1. Validate `content` — 400 if empty/whitespace
2. Validate `session_id` belongs to `kb_id` — 404 if not found
3. Validate KB exists and has at least one `complete` document — 404 / 409 if not
4. Fetch last `CHAT_HISTORY_WINDOW` messages for `session_id` (ordered by `created_at DESC`)
5. Reverse to chronological order; format as labelled history prefix (see research.md §1)
6. Assemble `question = history_prefix + "\n\nUser: " + content` (or bare `content` if no history)
7. Open DB transaction; INSERT user message row (not yet committed)
8. Call `POST /kbs/{kb_id}/query` sidecar with assembled `question` (outside transaction)
9. On sidecar success: INSERT assistant message row; commit transaction; UPDATE session `updated_at`
10. On sidecar failure: ROLLBACK transaction; return error to caller
11. If this is the first message: UPDATE `chat_sessions.title` (same transaction as step 9)
12. Return assembled response to caller

**Error Responses**

| Status | When |
|---|---|
| `400 Bad Request` | `content` is empty or whitespace-only |
| `404 Not Found` | `session_id` not found, or `session_id` doesn't belong to `kb_id`, or `kb_id` not found |
| `409 Conflict` | KB has no compiled documents (no `status = 'complete'` document exists) |
| `502 Bad Gateway` | Sidecar returned a non-2xx error response |
| `503 Service Unavailable` | Sidecar process failed to start or is unreachable |
| `504 Gateway Timeout` | Sidecar call exceeded `SIDECAR_TIMEOUT` |
| `422 Unprocessable Entity` | Path parameter UUID validation failure |

---

## Endpoint 3: Get Message History

### `GET /kbs/{kb_id}/chat/sessions/{session_id}/messages`

Returns the full chronologically-ordered message history for a session.

**Path Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `kb_id` | UUID string | Yes | Must match the KB that owns the session |
| `session_id` | UUID string | Yes | The session whose history to retrieve |

**Request Body**: None

**Success Response — `200 OK`**

```json
{
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "messages": [
    {
      "message_id": "a1b2c3d4-...",
      "role":       "user",
      "content":    "What is PageIndex?",
      "citations":  null,
      "token_cost": null,
      "created_at": "2026-06-21T15:01:00Z"
    },
    {
      "message_id": "7c9e6679-...",
      "role":       "assistant",
      "content":    "PageIndex is a document indexing technique that ...",
      "citations":  [ { "title": "...", "source": "...", "snippet": "..." } ],
      "token_cost": 412,
      "created_at": "2026-06-21T15:01:05Z"
    }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `session_id` | UUID string | Echoes the path parameter |
| `messages` | array | Chronologically ordered (oldest first); empty array if no messages |
| `messages[].message_id` | UUID string | Row ID |
| `messages[].role` | string | `"user"` or `"assistant"` |
| `messages[].content` | string | Message text |
| `messages[].citations` | array or null | Null for user messages; citation array for assistant messages |
| `messages[].token_cost` | integer or null | Null for user messages |
| `messages[].created_at` | ISO 8601 UTC | |

**Error Responses**

| Status | When |
|---|---|
| `404 Not Found` | `session_id` not found or doesn't belong to `kb_id` |
| `422 Unprocessable Entity` | Path parameter UUID validation failure |

---

## Endpoint 4: List Sessions

### `GET /kbs/{kb_id}/chat/sessions`

Returns all non-deleted chat sessions for the specified knowledge base.

**Path Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `kb_id` | UUID string | Yes | The knowledge base to list sessions for |

**Query Parameters**: None in Phase 0 (no pagination, filtering, or sorting parameters)

**Request Body**: None

**Success Response — `200 OK`**

```json
{
  "kb_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "sessions": [
    {
      "session_id": "3fa85f64-...",
      "title":      "What is PageIndex and how does it d…",
      "via":        "web",
      "created_at": "2026-06-21T15:00:00Z",
      "updated_at": "2026-06-21T15:01:05Z"
    },
    {
      "session_id": "11111111-...",
      "title":      null,
      "via":        "web",
      "created_at": "2026-06-21T14:55:00Z",
      "updated_at": "2026-06-21T14:55:00Z"
    }
  ]
}
```

Sessions are ordered by `created_at DESC` (newest first).

| Field | Type | Notes |
|---|---|---|
| `kb_id` | UUID string | Echoes the path parameter |
| `sessions` | array | Empty array if no sessions exist |
| `sessions[].session_id` | UUID string | |
| `sessions[].title` | string or null | Null if no messages have been sent yet |
| `sessions[].via` | string | `"web"` for all Phase 0 sessions |
| `sessions[].created_at` | ISO 8601 UTC | |
| `sessions[].updated_at` | ISO 8601 UTC | Refreshed on every new message |

**Error Responses**

| Status | When |
|---|---|
| `404 Not Found` | `kb_id` does not exist in `knowledge_bases` |
| `422 Unprocessable Entity` | Path parameter UUID validation failure |

---

## Environment Variables (additions to spec 003 `env-config.md`)

| Variable | Default | Description |
|---|---|---|
| `CHAT_HISTORY_WINDOW` | `20` | Number of message rows to include in assembled history prefix. Applied as `LIMIT` on `chat_messages` ordered by `created_at DESC`. Must be a positive integer; falls back to 20 if zero, negative, or non-integer. |

This variable supplements — and does not replace — the environment variables defined in spec 003's
`env-config.md` (`DATABASE_URL`, `BLOB_*`, `SIDECAR_*`, etc.).

---

## Router Registration

The four endpoints are registered on a FastAPI `APIRouter` with `prefix="/kbs/{kb_id}/chat"` and
`tags=["chat"]`. The router is included in the main `app.py` alongside the existing KB/query
router:

```python
# openkb/api/app.py  (conceptual — exact implementation in tasks.md)
from openkb.api.routes.chat import router as chat_router
app.include_router(chat_router)
```

No changes are required to the existing `kb.py` routes.
