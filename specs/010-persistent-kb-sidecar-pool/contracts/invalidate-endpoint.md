# Contract: POST /kbs/{kb_id}/invalidate

**Feature**: 010-persistent-kb-sidecar-pool
**Phase**: 1 — Design
**Date**: 2026-06-26
**Status**: New endpoint

---

## Purpose

Notifies the `generator_api` that a KB's compiled content has changed and its cached sidecar
should be marked stale. The next query to the KB will trigger a fresh blob sync and sidecar
restart. Called by `compiler_worker` after a document transitions to `complete` status.

This endpoint is **internal** — it is only reachable within the Docker Compose network (service
name `generator-api`). Authentication is explicitly out of scope for this feature iteration.

---

## Request

```
POST /kbs/{kb_id}/invalidate
Content-Type: application/json
```

### Path Parameters

| Parameter | Type | Required | Validation | Description |
|-----------|------|----------|------------|-------------|
| `kb_id` | UUID (string) | Yes | Valid RFC 4122 UUID; FastAPI `uuid.UUID` type enforces format | The knowledge base to invalidate |

### Request Body

```json
{
  "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string (UUID) | No | The document that triggered the invalidation. Used for logging and tracing only; does not affect pool behaviour. |

The body is optional. A request with no body or an empty body `{}` is also valid.

---

## Responses

### 204 No Content — Success

The KB has been marked stale (or was not present in the pool; both are valid no-op cases).
No response body.

```
HTTP/1.1 204 No Content
```

### 404 Not Found — KB does not exist in the system

Returned when `kb_id` does not correspond to any row in the `knowledge_bases` table
(i.e., the KB itself is unknown, not just absent from the pool).

```json
{
  "detail": "Knowledge base <kb_id> not found"
}
```

**Note**: A KB that exists in the database but has no running sidecar returns **204**, not 404.
Invalidating an idle (not-running) sidecar is a valid no-op.

### 422 Unprocessable Entity — Invalid `kb_id` format

Returned by FastAPI validation when `kb_id` cannot be parsed as a UUID.

```json
{
  "detail": [
    {
      "type": "uuid_parsing",
      "loc": ["path", "kb_id"],
      "msg": "Input should be a valid UUID",
      "input": "not-a-uuid"
    }
  ]
}
```

---

## Caller Contract (`compiler_worker`)

```python
# compiler_worker/job.py — after document status = 'complete'
async with httpx.AsyncClient(timeout=5.0) as client:
    try:
        response = await client.post(
            f"{config.generator_api_url}/kbs/{kb_id}/invalidate",
            json={"document_id": str(document_id)},
        )
        response.raise_for_status()
    except Exception:
        logger.warning(
            "Failed to notify generator_api of invalidation for kb_id=%s; "
            "next query will serve stale content until manual refresh",
            kb_id,
        )
```

**Fire-and-forget semantics**: the `await` is present to avoid premature task cancellation, but
any exception (connection refused, timeout, non-2xx) is caught and logged at WARNING. The job
is considered complete regardless of whether the notification succeeded.

---

## Pool Behaviour

The endpoint calls `SidecarPool.invalidate(kb_id)`:

```
if entry exists in pool:
    entry.stale = True
    log INFO: "KB {kb_id} marked stale (document_id={document_id})"
else:
    log DEBUG: "invalidate called for KB {kb_id} with no active sidecar — no-op"
```

The stale sidecar is NOT stopped immediately. It will be stopped and replaced on the next
`get_or_start()` call for that KB.

---

## Security Notes

- `kb_id` is validated as a UUID before any pool or database operation; malformed inputs are
  rejected with 422 before reaching the pool.
- No authentication on this endpoint in this feature iteration. Assumed network-isolated within
  Docker Compose. **MUST be secured before external/cloud exposure.**
- The `document_id` field is logged but never used in any filesystem or subprocess operation.
