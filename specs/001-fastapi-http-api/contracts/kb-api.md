# API Contract: OpenKB HTTP API

**Version**: 0.1.0 (feature `001-fastapi-http-api`)
**Base URL**: `http://<host>:<port>` (default `http://localhost:8000`)
**Content-Type**: `application/json` for all requests and responses
**Auth**: None (trusted internal environment — Assumption)

---

## Common Response Shape

### Success responses

All successful responses are JSON objects whose schema is documented per
endpoint. HTTP 200 is returned for all successful operations.

### Error responses

All error responses share a single schema regardless of status code:

```json
{
  "detail": "<human-readable, actionable message>"
}
```

| Status | Condition |
|--------|-----------|
| 422 | Request body fails Pydantic validation (FastAPI automatic) |
| 404 | KB does not exist at the given `kb_name` |
| 409 | KB already exists (init conflict) |
| 422 | Semantic validation failure (unsupported extension, URL fetch error) |
| 502 | LLM API failure |
| 503 | KB is busy (Azure Blob Lease timeout) |

---

## `POST /kb/init`

Initialise a new knowledge base.

### Request

```json
{
  "kb_name": "my-kb",
  "model": "gpt-5.4-mini",
  "language": "en"
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `kb_name` | string | ✅ | `[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]` or single `[a-z0-9]`; max 64 chars |
| `model` | string \| null | ❌ | max 100 chars; no `\n\r\t`; defaults to `"gpt-5.4-mini"` |
| `language` | string \| null | ❌ | max 50 chars; no `\n\r\t`; defaults to `"en"` |

### Success Response — `200 OK`

```json
{
  "kb_name": "my-kb",
  "status": "created",
  "message": "Knowledge base 'my-kb' initialised."
}
```

`status` is `"created"` when the KB was created, `"exists"` when it already
existed (409 path — see below).

### Error Responses

**`409 Conflict`** — KB already exists:
```json
{ "detail": "Knowledge base 'my-kb' already initialised." }
```

**`422 Unprocessable Entity`** — Validation failure (e.g. `kb_name` contains
uppercase letters, `model` contains a newline):
```json
{
  "detail": [
    {
      "type": "string_pattern_mismatch",
      "loc": ["body", "kb_name"],
      "msg": "String should match pattern ...",
      "input": "My-KB"
    }
  ]
}
```
*(FastAPI's standard 422 shape — array of validation errors.)*

### Side Effects

Creates the following filesystem / blob structure:
```
<kb_name>/
├── .openkb/
│   ├── config.yaml        # model, language, pageindex_threshold
│   ├── hashes.json        # {}
│   └── ingest.lock        # empty lock blob (Azure) or lock file
├── wiki/
│   ├── AGENTS.md
│   ├── index.md
│   ├── log.md
│   ├── summaries/
│   ├── concepts/
│   ├── entities/
│   └── sources/
│       └── images/
└── raw/
```

---

## `POST /kb/add`

Ingest a document into an existing KB. The operation is synchronous — the
response is returned only after the document has been fully compiled.

### Request

```json
{
  "kb_name": "my-kb",
  "source": "https://arxiv.org/pdf/2304.01373"
}
```

`source` may be:
- A URL (`http://` or `https://`) — fetched to a temp buffer, saved to `raw/`,
  then processed. PDF and HTML content types are supported.
- A local file path accessible to the server process (for local storage backend).

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `kb_name` | string | ✅ | slug pattern |
| `source` | string | ✅ | non-blank; URL or local path |

### Success Response — `200 OK`

**Document added**:
```json
{
  "status": "added",
  "doc_name": "attention-is-all-you-need-a1b2c3d4",
  "message": "Document added successfully."
}
```

**Document already in KB (hash match)**:
```json
{
  "status": "skipped",
  "doc_name": "attention-is-all-you-need-a1b2c3d4",
  "message": "Document already in knowledge base (hash match)."
}
```

| Field | Type | Values |
|-------|------|--------|
| `status` | string | `"added"` \| `"skipped"` \| `"failed"` |
| `doc_name` | string \| null | slug of ingested document; null on failure |
| `message` | string | human-readable |

### Error Responses

**`404 Not Found`** — KB not initialised:
```json
{ "detail": "Knowledge base 'my-kb' not found. Call POST /kb/init to create it." }
```

**`422 Unprocessable Entity`** — Unsupported file extension:
```json
{
  "detail": "Unsupported file type '.zip'. Supported: .csv, .docx, .html, .htm, .md, .markdown, .pdf, .pptx, .txt, .xls, .xlsx"
}
```

**`422 Unprocessable Entity`** — URL fetch failed:
```json
{ "detail": "Failed to fetch URL 'https://...': HTTP 404 from server." }
```

**`502 Bad Gateway`** — LLM API failure:
```json
{ "detail": "LLM API error during compilation: AuthenticationError — Invalid API key." }
```

**`503 Service Unavailable`** — KB busy (Azure lease):
```json
{ "detail": "Knowledge base 'my-kb' is busy; retry after a moment." }
```

---

## `POST /kb/query`

Answer a natural language question against an existing KB.

### Request

```json
{
  "kb_name": "my-kb",
  "question": "What is the attention mechanism?",
  "save": false
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `kb_name` | string | ✅ | slug pattern |
| `question` | string | ✅ | min 1 char after strip |
| `save` | boolean | ❌ | default `false`; saves answer to `wiki/explorations/` |

### Success Response — `200 OK`

```json
{
  "answer": "The attention mechanism is a technique that allows...",
  "saved_to": null
}
```

When `save=true`:
```json
{
  "answer": "The attention mechanism is a technique that allows...",
  "saved_to": "my-kb/wiki/explorations/what-is-the-attention-mechanism.md"
}
```

When KB has no compiled content, the answer reflects the empty state (same as
`openkb query` CLI behaviour) — this is **not** an error:
```json
{
  "answer": "The knowledge base does not contain any compiled documents yet.",
  "saved_to": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `answer` | string | LLM answer; may be empty string |
| `saved_to` | string \| null | path/blob where answer was saved; null if not saved |

### Error Responses

**`404 Not Found`** — KB not initialised:
```json
{ "detail": "Knowledge base 'my-kb' not found. Call POST /kb/init to create it." }
```

**`422 Unprocessable Entity`** — Blank question:
```json
{
  "detail": [
    { "type": "string_too_short", "loc": ["body", "question"], "msg": "..." }
  ]
}
```

**`502 Bad Gateway`** — LLM failure:
```json
{ "detail": "LLM API error during query: RateLimitError — Too many requests." }
```

**`503 Service Unavailable`** — KB busy (rare; query acquires a read lock):
```json
{ "detail": "Knowledge base 'my-kb' is busy; retry after a moment." }
```

---

## `GET /kb/list`

List all documents and wiki content in an existing KB.

### Request

Query parameters:
| Parameter | Type | Required | Constraints |
|-----------|------|----------|-------------|
| `kb_name` | string | ✅ | slug pattern |

**Example**: `GET /kb/list?kb_name=my-kb`

### Success Response — `200 OK`

```json
{
  "documents": [
    {
      "name": "attention-is-all-you-need.pdf",
      "doc_name": "attention-is-all-you-need-a1b2c3d4",
      "type": "pageindex"
    },
    {
      "name": "introduction.md",
      "doc_name": "introduction-b5c6d7e8",
      "type": "short"
    }
  ],
  "summaries": ["attention-is-all-you-need-a1b2c3d4", "introduction-b5c6d7e8"],
  "concepts": ["transformer-architecture", "self-attention"],
  "entities": ["google-brain", "ashish-vaswani"],
  "reports": ["lint_20260619_103000.md"]
}
```

When KB is empty:
```json
{
  "documents": [],
  "summaries": [],
  "concepts": [],
  "entities": [],
  "reports": []
}
```

| Field | Type | Description |
|-------|------|-------------|
| `documents` | `DocumentItem[]` | indexed documents (name, doc_name, type) |
| `summaries` | `string[]` | sorted stems of `wiki/summaries/*.md` |
| `concepts` | `string[]` | sorted stems of `wiki/concepts/*.md` |
| `entities` | `string[]` | sorted stems of `wiki/entities/*.md` |
| `reports` | `string[]` | sorted filenames of `wiki/reports/*.md` |

### Error Responses

**`404 Not Found`** — KB not initialised:
```json
{ "detail": "Knowledge base 'my-kb' not found. Call POST /kb/init to create it." }
```

---

## `GET /kb/status`

Return health metrics for an existing KB.

### Request

Query parameters:
| Parameter | Type | Required | Constraints |
|-----------|------|----------|-------------|
| `kb_name` | string | ✅ | slug pattern |

**Example**: `GET /kb/status?kb_name=my-kb`

### Success Response — `200 OK`

```json
{
  "kb_name": "my-kb",
  "total_indexed": 2,
  "last_compile": "2026-06-19T10:15:00Z",
  "last_lint": "2026-06-19T09:00:00Z",
  "directory_counts": {
    "sources": 2,
    "summaries": 2,
    "concepts": 5,
    "entities": 3,
    "reports": 1,
    "raw": 2
  }
}
```

When KB has no compiled content:
```json
{
  "kb_name": "my-kb",
  "total_indexed": 0,
  "last_compile": null,
  "last_lint": null,
  "directory_counts": {
    "sources": 0,
    "summaries": 0,
    "concepts": 0,
    "entities": 0,
    "reports": 0,
    "raw": 0
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `kb_name` | string | KB slug |
| `total_indexed` | integer | number of entries in `hashes.json` |
| `last_compile` | string \| null | ISO-8601 UTC mtime of newest file in summaries/, concepts/, entities/ |
| `last_lint` | string \| null | ISO-8601 UTC mtime of newest report in reports/ |
| `directory_counts` | object | file count per subdirectory |

### Error Responses

**`404 Not Found`** — KB not initialised:
```json
{ "detail": "Knowledge base 'my-kb' not found. Call POST /kb/init to create it." }
```

---

## Full Endpoint Summary

| Method | Path | Auth | Request | Success | Key Errors |
|--------|------|------|---------|---------|------------|
| POST | `/kb/init` | — | JSON body | 200 created/exists | 409, 422 |
| POST | `/kb/add` | — | JSON body | 200 added/skipped | 404, 422, 502, 503 |
| POST | `/kb/query` | — | JSON body | 200 answer | 404, 422, 502 |
| GET | `/kb/list` | — | query param | 200 document list | 404 |
| GET | `/kb/status` | — | query param | 200 health metrics | 404 |

---

## Contract Test Assertions

The following invariants MUST be verified by `tests/contract/test_api_contracts.py`:

1. `POST /kb/init` response body always contains `kb_name`, `status`, `message`.
2. `status` in init response is exactly `"created"` or `"exists"`.
3. `POST /kb/add` response body always contains `status`, `message`.
4. `status` in add response is exactly `"added"`, `"skipped"`, or `"failed"`.
5. `POST /kb/query` response body always contains `answer` and `saved_to`.
6. `GET /kb/list` response body always contains all five array fields.
7. `GET /kb/status` response body always contains `kb_name`, `total_indexed`,
   `last_compile`, `last_lint`, `directory_counts`.
8. `directory_counts` always contains at minimum `summaries`, `concepts`, `entities`.
9. All error responses from 4xx / 5xx handlers contain a `detail` string field.
10. `last_compile` and `last_lint` are either `null` or a valid ISO-8601 string.
