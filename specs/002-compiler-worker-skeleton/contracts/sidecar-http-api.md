# Contract: Sidecar HTTP API

**Feature**: `003-compiler-worker-skeleton`  
**Date**: 2026-06-21  
**Sidecar branch**: `001-fastapi-http-api` (OpenKB upstream FastAPI app)  
**Base URL**: `http://127.0.0.1:{port}` (port is OS-assigned per job)  
**Auth**: None (localhost only; no token or API key required in Phase 0)

---

## Overview

The sidecar is a short-lived FastAPI process wrapping the OpenKB CLI. It is
started per job with its working directory set to the job's scratch directory
(e.g. `/tmp/openkb-job-abc123`). All file paths in requests are relative to
this CWD. The three Phase 0 endpoints mirror the three CLI operations:
`openkb init`, `openkb add`, `openkb status`.

---

## Startup

The worker spawns the sidecar with:

```bash
uvicorn openkb.api.app:app --host 127.0.0.1 --port {port} --workers 1
# CWD is set to the scratch directory via Popen(cwd=scratch_dir)
```

The worker polls `GET /health` up to 30 times × 0.5 s (= 15 s max) before
declaring the sidecar failed to start.

---

## Endpoints

### `GET /health`

**Purpose**: Liveness check; used by the worker after spawn to confirm the
sidecar is accepting connections.

**Request**: No body.

**Response** `200 OK`:
```json
{ "status": "ok" }
```

---

### `POST /init`

**Purpose**: Initialise the KB working tree in the sidecar's CWD. Creates
`.openkb/config.yaml`, `wiki/`, `raw/`, and all required subdirectories —
equivalent to running `openkb init --model {model} --language {language}`.

**Request body** (`application/json`):
```json
{
  "model":    "gpt-5.4-mini",
  "language": "en"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `model` | string | ✅ | LiteLLM provider/model string (e.g. `gpt-5.4-mini`); read from `knowledge_bases.compilation_config.model` |
| `language` | string | ✅ | ISO 639-1 language code or full name (e.g. `en`, `Korean`); read from `knowledge_bases.compilation_config.language` |

**Response** `200 OK`:
```json
{ "status": "ok" }
```

**Error** `409 Conflict` (KB already initialised in CWD):
```json
{ "detail": "Knowledge base already initialized." }
```

**Error** `422 Unprocessable Entity` (validation failure):
```json
{ "detail": [{ "loc": ["body", "model"], "msg": "field required" }] }
```

---

### `POST /add`

**Purpose**: Submit a document for compilation. The file MUST already exist
at `{scratch_dir}/raw/{filename}`. Triggers the async OpenKB compilation
pipeline (LLM calls). Returns immediately with a `job_id`; the worker polls
`GET /status` to track progress.

**Request body** (`application/json`):
```json
{
  "filename": "report.md"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `filename` | string | ✅ | Filename of the source document under `raw/` in the sidecar CWD |

**Response** `202 Accepted`:
```json
{ "job_id": "internal-uuid-or-opaque-token" }
```

**Error** `404 Not Found` (file not in `raw/`):
```json
{ "detail": "File not found: raw/report.md" }
```

**Error** `409 Conflict` (compilation already in progress):
```json
{ "detail": "Compilation already in progress." }
```

**Error** `422 Unprocessable Entity` (unsupported file type):
```json
{ "detail": "Unsupported file type: .xyz" }
```

---

### `GET /status`

**Purpose**: Poll the current compilation state. The worker calls this
endpoint in a loop (every `SIDECAR_POLL_INTERVAL_S` seconds, default 2 s)
until `status` is `complete` or `failed`, or until `SIDECAR_COMPILE_TIMEOUT_S`
elapses.

**Request**: No body.

**Response** `200 OK` — compilation in progress:
```json
{
  "status":        "compiling",
  "pages":         [],
  "token_cost":    null,
  "pageindex_used": null,
  "error":         null
}
```

**Response** `200 OK` — compilation succeeded:
```json
{
  "status": "complete",
  "pages": [
    {
      "slug":        "summaries/report",
      "page_type":   "summary",
      "entity_type": null,
      "file_path":   "wiki/summaries/report.md"
    },
    {
      "slug":        "concepts/attention",
      "page_type":   "concept",
      "entity_type": null,
      "file_path":   "wiki/concepts/attention.md"
    },
    {
      "slug":        "entities/alan-turing",
      "page_type":   "entity",
      "entity_type": "person",
      "file_path":   "wiki/entities/alan-turing.md"
    }
  ],
  "token_cost":    1847,
  "pageindex_used": false,
  "error":         null
}
```

**Response** `200 OK` — compilation failed:
```json
{
  "status":         "failed",
  "pages":          [],
  "token_cost":     null,
  "pageindex_used": null,
  "error":          "LLM returned empty content for concept 'attention'"
}
```

**Response** `200 OK` — no job started yet:
```json
{
  "status":         "idle",
  "pages":          [],
  "token_cost":     null,
  "pageindex_used": null,
  "error":          null
}
```

### `GET /status` — Pages Array Schema

Each object in the `pages` array:

| Field | Type | Nullable | Description |
|---|---|---|---|
| `slug` | string | ✗ | Wiki page slug without `.md` extension (e.g. `summaries/report`). Unique within a KB — maps to `wiki_pages.slug` |
| `page_type` | string | ✗ | One of: `summary`, `concept`, `entity`, `index` |
| `entity_type` | string | ✅ | Only set when `page_type == "entity"`; one of the `DEFAULT_ENTITY_TYPES` values (e.g. `person`, `organization`, `place`) |
| `file_path` | string | ✗ | Relative path within the sidecar CWD (e.g. `wiki/summaries/report.md`); used to read and upload the file content to Blob Storage |

---

## Worker Polling Loop

```python
deadline = time.monotonic() + config.sidecar_compile_timeout
while time.monotonic() < deadline:
    status = sidecar.get_status()           # GET /status
    if status.status == "complete":
        return status                       # success path
    if status.status == "failed":
        raise SidecarCompileError(status.error)
    time.sleep(config.sidecar_poll_interval)
# deadline exceeded
sidecar.teardown()
raise SidecarTimeoutError(f"Compilation did not complete within {config.sidecar_compile_timeout}s")
```

---

## Teardown

After every job (success or failure), the worker:
1. Sends `SIGTERM` to the sidecar process.
2. Waits up to 5 seconds for graceful shutdown.
3. Sends `SIGKILL` if the process has not exited.
4. Calls `shutil.rmtree(scratch_dir, ignore_errors=True)`.

---

## Constraints

- The sidecar binds to `127.0.0.1` only — never `0.0.0.0`.
- One sidecar per job; never shared across jobs or KBs.
- No authentication on any endpoint in Phase 0.
- The sidecar does not need to be idempotent across jobs; each job gets a
  fresh process and scratch directory.
