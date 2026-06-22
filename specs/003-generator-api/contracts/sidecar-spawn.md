# Contract: Per-Request Sidecar Spawn (Generator API)

**Branch**: `004-generator-api` | **Date**: 2026-06-21
**Service**: `generator_api`
**Related**: [`specs/002-compiler-worker-skeleton/contracts/sidecar-http-api.md`](../../002-compiler-worker-skeleton/contracts/sidecar-http-api.md)

---

## Purpose

Defines the per-request sidecar lifecycle used by the generator-api. This is a query-only
variant of the sidecar pattern established for compiler-worker. The key difference: compiler-worker
uses sidecar for document compilation (init → add → poll status); generator-api uses sidecar for
querying an already-compiled wiki tree (init → query).

---

## Sidecar Lifecycle per Query Request

```
Request arrives
      │
      ▼
1. Allocate dynamic port (socket bind-to-0)
      │
      ▼
2. Create scratch dir: {SCRATCH_DIR_ROOT}/{request_id}/kbs/
      │
      ▼
3. Sync wiki tree from Azurite
   LIST  container={AZURE_KB_CONTAINER}, prefix={storage_container_path}/wiki/
   GET   each blob → {scratch_dir}/{kb_slug}/wiki/{relative_path}
      │
      ▼
4. Spawn sidecar subprocess
   cmd:  openkb serve --host 127.0.0.1 --port {port}
   env:  OPENKB_STORAGE_BACKEND=local
         OPENKB_BASE_DIR={scratch_dir}  ← contains {kb_slug}/wiki/
         LLM_API_KEY={forwarded}
      │
      ▼
5. Wait for sidecar readiness
   poll: GET http://127.0.0.1:{port}/openapi.json
   until: HTTP 200  OR  elapsed > SIDECAR_STARTUP_TIMEOUT → raise SidecarStartError
      │
      ▼
6. Init KB in sidecar
   POST /kb/init  body: { kb_name: {kb_slug} }
   expect: status 200 (created or exists)
      │
      ▼
7. Query sidecar
   POST /kb/query  body: { kb_name: {kb_slug}, question: {question}, save: false }
   expect: HTTP 200  { answer, saved_to }
   timeout: GENERATOR_REQUEST_TIMEOUT (outer asyncio.wait_for)
      │
      ▼
8. Return response to caller
      │
      ▼ (finally — always executes)
9. Teardown
   proc.terminate() → wait(timeout=5) → proc.kill() if still running
   shutil.rmtree(scratch_dir, ignore_errors=True)
```

---

## Isolation Guarantees

| Property | Guarantee |
|----------|-----------|
| **Port** | Unique per request; dynamically allocated; bound to `127.0.0.1` only |
| **Scratch dir** | Unique per request (`{SCRATCH_DIR_ROOT}/{request_id}/kbs/`); deleted in `finally` |
| **Sidecar process** | One per request; never shared across concurrent requests or KBs |
| **No state leak** | `finally` block runs even on exception, timeout, or signal |
| **KB identity** | Sidecar reads only `{scratch_dir}/{kb_slug}/wiki/` — no access to other KBs |

---

## Error Handling

| Step | Failure | HTTP Response |
|------|---------|---------------|
| 3 — blob sync | Azurite unreachable | 503 `Blob storage unavailable` |
| 3 — blob sync | Any blob download fails | 503 `Wiki sync failed` |
| 3 — blob sync | Zero blobs found (empty wiki) | 503 `Wiki is empty for KB {kb_id}` |
| 4 — spawn | `openkb` not found in PATH | 502 `Sidecar binary not found` |
| 5 — ready | Timeout before HTTP 200 | 503 `Sidecar failed to become ready in {N}s` |
| 6 — init | Non-200 from sidecar | 502 `Sidecar init failed: {detail}` |
| 7 — query | Non-200 from sidecar | 502 `Sidecar query failed: {detail}` |
| 7 — query | asyncio.TimeoutError | 504 `Query timed out after {N}s` |
| 9 — teardown | Teardown always runs; errors are logged as WARNING, not re-raised | — |

---

## Subprocess Environment

```python
import os

sidecar_env = {
    **os.environ,                               # Inherit PATH etc. from parent
    "OPENKB_STORAGE_BACKEND": "local",
    "OPENKB_BASE_DIR": str(scratch_dir),        # {SCRATCH_DIR_ROOT}/{request_id}/kbs/
    "LLM_API_KEY": settings.llm_api_key,
    # Strip Azure env vars from sidecar subprocess — sidecar uses local storage only
    # This prevents sidecar from accidentally writing to Azurite
    "AZURE_STORAGE_CONNECTION_STRING": "",
    "AZURE_KB_CONTAINER": "",
}
```

Stripping Azure env vars from the sidecar subprocess prevents accidental blob writes during the
query phase — the sidecar must only read from the local scratch filesystem.

---

## Port Allocation

```python
import socket

def allocate_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
```

TOCTOU window between `sock.close()` and uvicorn binding is acceptable for Phase 0
(single-request-at-a-time; low concurrency; localhost only).

---

## Differences from Compiler-Worker Sidecar Pattern

| Aspect | Compiler-Worker | Generator-API |
|--------|----------------|---------------|
| Sidecar endpoints used | `POST /kb/init`, `POST /kb/add`, `GET /kb/status` | `POST /kb/init`, `POST /kb/query` |
| Wiki tree direction | Sidecar writes → compiler-worker uploads to blob | Blob download → sidecar reads |
| Per-job vs per-request | Per compilation job | Per HTTP query request |
| Timeout | `COMPILATION_TIMEOUT` (long — LLM compile time) | `GENERATOR_REQUEST_TIMEOUT` (shorter — query only) |
| Stale cleanup | On startup: stale `compiling` docs | N/A — stateless between requests |
