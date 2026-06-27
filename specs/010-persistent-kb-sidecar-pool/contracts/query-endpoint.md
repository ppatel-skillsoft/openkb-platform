# Contract: POST /kbs/{kb_id}/query

**Feature**: 010-persistent-kb-sidecar-pool
**Phase**: 1 — Design
**Date**: 2026-06-26
**Status**: Existing endpoint — unchanged signature; pool-backed implementation

---

## Purpose

Answers a natural-language question against a compiled knowledge base. This endpoint's external
contract (URL, request body, response shape) is **unchanged** by this feature. Internally, the
sidecar lifecycle is now managed by `SidecarPool` rather than being per-request ephemeral.

This document captures the current contract for reference and notes the implementation changes
that affect observable behaviour (latency, error codes for new failure modes).

---

## Request

```
POST /kbs/{kb_id}/query
Content-Type: application/json
```

### Path Parameters

| Parameter | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `kb_id` | UUID (string) | Yes | Valid RFC 4122 UUID | The knowledge base to query |

### Request Body

```json
{
  "question": "What is the Hertzsprung-Russell diagram?",
  "save": false
}
```

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `question` | string | Yes | 1–8000 chars (non-blank) | The natural-language question |
| `save` | bool | No | Default `false` | Reserved; has no effect in current implementation |

---

## Responses

### 200 OK — Answer returned

```json
{
  "answer": "The Hertzsprung-Russell diagram is a scatter plot...",
  "citations": [
    { "page": "stellar_evolution", "snippet": "..." }
  ],
  "tokens_used": 412
}
```

| Field | Type | Always present | Description |
|-------|------|----------------|-------------|
| `answer` | string | Yes | The grounded answer from the sidecar |
| `citations` | array | Yes | Source page references (may be empty) |
| `tokens_used` | int | Yes | LLM tokens consumed (0 if not reported by sidecar) |

### 404 Not Found — KB does not exist

```json
{ "detail": "Knowledge base <kb_id> not found" }
```

### 409 Conflict — KB has no compiled documents

```json
{ "detail": "Knowledge base <kb_id> has no compiled documents" }
```

### 502 Bad Gateway — Sidecar start failure

```json
{ "detail": "Sidecar failed to start: <reason>" }
```

**New in this feature**: also returned when a crashed sidecar cannot be restarted.

### 503 Service Unavailable — Blob sync failure

```json
{ "detail": "<blob sync error message>" }
```

### 504 Gateway Timeout — Query or startup timeout

```json
{ "detail": "Query timed out after 120s" }
```

**Changed in this feature**: timeout default reduced from 300 s to 120 s (configurable via
`GENERATOR_REQUEST_TIMEOUT`). Startup timeout (cold start) is governed separately by
`GENERATOR_SIDECAR_STARTUP_TIMEOUT` (default 30 s).

### 422 Unprocessable Entity — Invalid input

FastAPI validation error (malformed `kb_id` or invalid request body).

---

## Observable Behaviour Changes (this feature)

| Aspect | Before (ephemeral) | After (pool-backed) |
|--------|--------------------|---------------------|
| Warm query latency | 5–15 s (cold every time) | < 2 s (no blob sync or process spawn) |
| Cold query latency | 5–15 s | 5–15 s (unchanged, only on first request or post-invalidation) |
| Concurrent same-KB requests | Each spawns its own sidecar | All wait for one shared sidecar; no duplicate spawns |
| Sidecar lifecycle scope | Per-request; torn down in `finally` | Persistent; torn down on eviction/invalidation/shutdown |
| Scratch directory | Temp UUID dir, cleaned per-request | `{scratch_root}/{kb_id}/`, cleaned on sidecar stop |
| Query timeout default | 300 s | 120 s |

---

## Implementation Note

The route handler in `router.py` is refactored to:

```python
@router.post("/kbs/{kb_id}/query", response_model=QueryResponse)
async def query_kb(
    kb_id: uuid.UUID,
    body: QueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    pool: SidecarPool = request.app.state.pool
    # ... DB pre-flight (unchanged) ...
    sidecar = await pool.get_or_start(kb_id_str, kb_slug, container)
    answer, citations, tokens_used = await asyncio.wait_for(
        asyncio.to_thread(sidecar.query, kb_slug, body.question),
        timeout=settings.generator_request_timeout,
    )
    pool.update_last_used(kb_id_str)
    return QueryResponse(answer=answer, citations=citations, tokens_used=tokens_used)
```

The `try/finally` block that called `sidecar.teardown()` and `shutil.rmtree` is removed.
Teardown is now the pool's responsibility.
