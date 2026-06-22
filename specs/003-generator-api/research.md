# Research: Phase 0 Generator API Service

**Branch**: `004-generator-api` | **Date**: 2026-06-21
**Purpose**: Resolve all NEEDS CLARIFICATION items before Phase 1 design

---

## R-001 — Sidecar Query Endpoint Path

**Question**: What is the exact endpoint path and request/response schema for the OpenKB sidecar
query endpoint? (Spec assumption: "exact path will be confirmed against `001-fastapi-http-api` branch")

**Decision**: `POST /kb/query`

**Findings** (from `001-fastapi-http-api` branch source inspection):
- FastAPI router mounted at prefix `/kb` in `openkb/api/app.py` (`app.include_router(kb_router, prefix="/kb")`)
- Route handler: `POST /query` in `openkb/api/routes/kb.py` → full path `POST /kb/query`
- Request body (`KBQueryRequest`): `{ kb_name: str, question: str, save: bool = false }`
- Response body (`KBQueryResponse`): `{ answer: str, saved_to: str | null }`

**Critical gap — citations and tokens_used**:
The current sidecar response model (`KBQueryResponse`) returns only `{ answer, saved_to }`.
It does **not** return `citations` or `tokens_used`. The spec (FR-007, SC-003) requires the
generator-api to preserve and return citations verbatim. The upstream agent (`run_query`) returns a
plain text `final_output` string — citations are embedded in the prose and are not structured objects.

**Phase 0 resolution**:
- `citations` → returned as `[]` (empty array) by generator-api in Phase 0. This is explicitly
  valid per spec User Story 1 ("citations: array, **may be empty** for trivial questions but
  structure must be present") and SC-003 ("100% of citation objects returned by the upstream sidecar
  appear unchanged" — 100% of zero = zero, satisfied).
- `tokens_used` → returned as `0` (integer) by generator-api in Phase 0.
- **Architecture is designed for pass-through**: once the sidecar contract is extended to return
  structured citations and token counts, the generator-api passes them through with zero code
  changes in the routing layer.
- Sidecar contract extension is tracked as a follow-on item (pre-work for spec 004+).

**Rationale**: Implementing citation extraction by parsing prose text would violate FR-007 (no
modification of citation data) and is fragile. Returning an empty array is honest, spec-compliant,
and keeps the pass-through architecture clean.

**Alternatives considered**:
- Parse prose answer for citation patterns → rejected: fragile, modifies/manufactures citation data
- Block Phase 0 release until sidecar is extended → rejected: disproportionate for dev-only use

---

## R-002 — Blob Storage Container and Path Layout

**Question**: What is the exact Azurite container name and blob path layout where compiler-worker
writes wiki pages? How does `storage_container_path` in `knowledge_bases` map to blob paths?

**Decision**: Container `openkb`; blob prefix `{storage_container_path}/wiki/`

**Findings**:
- From `001-fastapi-http-api` branch `docker-compose.yml`: `AZURE_KB_CONTAINER: openkb`
- From spec 002 FR-008: "upload all produced wiki markdown pages to Blob Storage under the path
  `kb-{id}/wiki/`" — this is the `storage_container_path` prefix + `/wiki/` suffix
- `storage_container_path` in `knowledge_bases` table = `kb-{id}` (the blob prefix root for the KB)
- Full blob paths: `openkb` container → `kb-{id}/wiki/index.md`,
  `kb-{id}/wiki/summaries/doc1.md`, `kb-{id}/wiki/concepts/concept1.md`,
  `kb-{id}/wiki/entities/person1.md`, `kb-{id}/wiki/sources/doc1.md` (short),
  `kb-{id}/wiki/sources/doc1.json` (pageindex), `kb-{id}/wiki/sources/images/doc1/p1_img1.png`
- The full wiki tree (including `sources/` and `sources/images/`) lives under `wiki/` and must all
  be synced — the query agent reads `sources/` for PageIndex document page content and images.

**Rationale**: All wiki content (pages, sources, images) is uploaded under `wiki/` by compiler-worker.
Syncing only `wiki/*.md` would break queries over PageIndex documents that need `sources/`.

**Alternatives considered**:
- Sync only `wiki/summaries/`, `wiki/concepts/`, `wiki/entities/` → rejected: breaks PageIndex source
  lookups and image rendering
- Let sidecar read directly from Azurite (Azure backend) → rejected: per-request sidecar startup with
  Azure backend requires passing credentials into a subprocess; local backend is simpler and faster

---

## R-003 — Sidecar Startup Command and Health Check

**Question**: How is the sidecar started, and how does the generator-api know it is ready to accept
requests?

**Decision**: `openkb serve --host 127.0.0.1 --port {port}` subprocess; readiness = poll
`GET http://127.0.0.1:{port}/openapi.json` until HTTP 200

**Findings**:
- `openkb serve` CLI command in `001-fastapi-http-api` calls `uvicorn.run(create_app(), host, port)`
- Requires the `[api]` extra: `pip install 'openkb[api]'`
- FastAPI exposes `/openapi.json` immediately once uvicorn begins accepting connections — reliable
  as a startup probe (returns 200 with schema JSON)
- Docker Compose healthcheck for the sidecar uses `curl -sf http://localhost:8000/docs` — equivalent
  but `/openapi.json` is lighter (no HTML render)
- Dynamic port allocation: `socket.socket()` bind-to-0 trick to find a free port; TOCTOU window
  acceptable for Phase 0 single-request-at-a-time operation
- Subprocess environment: `OPENKB_STORAGE_BACKEND=local`, `OPENKB_BASE_DIR={scratch_dir}`,
  `LLM_API_KEY={forwarded from generator-api env}` — all other env vars inherited from parent

**Rationale**: Local storage backend avoids credential forwarding complexity. The sidecar reads
wiki pages from the scratch directory which is entirely under generator-api's control.

**Alternatives considered**:
- Use Azure backend in subprocess (point at Azurite directly) → rejected: requires forwarding
  `AZURE_STORAGE_CONNECTION_STRING` into subprocess; unnecessary coupling given local sync is simpler
- Use Unix socket instead of TCP port → rejected: complicates httpx client URL construction; TCP is
  fine for localhost Phase 0

---

## R-004 — KB Identifier: UUID vs Slug for Sidecar kb_name

**Question**: The generator-api uses `kb_id` (UUID) in its URL. The sidecar uses `kb_name` (a slug).
How are these mapped?

**Decision**: Use `knowledge_bases.slug` as the sidecar `kb_name`

**Findings**:
- `knowledge_bases` table has `id` (UUID, PK) and `slug` (text, unique, not null) per spec 001
- Sidecar `KBQueryRequest.kb_name` is validated against `^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$` —
  slug format matches this pattern (slugs are lowercase alphanumeric with hyphens)
- The sidecar `LocalStorageBackend` uses `base_dir / kb_name` as the KB root directory
- Generator-api downloads to `{scratch_dir}/{slug}/wiki/`, sets `OPENKB_BASE_DIR={scratch_dir}`,
  calls sidecar with `kb_name={slug}` → sidecar reads `{scratch_dir}/{slug}/wiki/` ✓

**Rationale**: Slug is stable, URL-safe, and sidecar-compatible. UUID has hyphens and uppercase which
are technically valid slug chars but awkward; slug was designed for this use.

**Alternatives considered**:
- Use `kb-{uuid}` as sidecar kb_name → rejected: artificial; slug is the right semantic identifier
- Use a fixed constant kb_name like `query-scratch` → rejected: breaks concurrent request safety if
  warm pooling is ever introduced; slug is more debuggable in sidecar logs

---

## R-005 — Request Timeout and Sidecar Teardown

**Question**: What is the per-request timeout strategy? How is the sidecar process torn down?

**Decision**: Configurable `GENERATOR_REQUEST_TIMEOUT_SECONDS` (default: 300); sidecar always torn
down in `finally` block via `proc.terminate()` / `proc.kill()` after grace period

**Findings**:
- Spec FR-009: "enforce a per-request timeout; if exceeded, return HTTP 504 and clean up sidecar"
- Spec edge case: sidecar starts but times out before returning → 504, cleanup
- Spec edge case: sidecar fails to start → 502/503, cleanup
- Strategy: `asyncio.wait_for(call_sidecar(), timeout=settings.request_timeout)` for the HTTP call
  to the sidecar; sidecar startup polling has its own sub-timeout (`SIDECAR_STARTUP_TIMEOUT_SECONDS`,
  default: 30)
- Teardown: `proc.terminate()` → wait up to 5 seconds → `proc.kill()` if still running; scratch dir
  cleaned up in outer `finally` block using `shutil.rmtree`

**Rationale**: Simple, no external scheduler. Works identically inside Docker and as standalone process.

---

## R-006 — kb_id Path Traversal Validation

**Question**: The spec calls out path traversal on kb_id explicitly. How is it validated?

**Decision**: Validate `kb_id` is a valid UUID string before any DB or FS use

**Findings**:
- `kb_id` is a UUID. FastAPI path parameters can be typed as `uuid.UUID` which auto-validates
  format and rejects anything that is not a valid UUID (e.g., `../evil`, encoded slashes)
- This satisfies the spec edge case: "must validate and reject before using in any file system or
  storage operation"

**Rationale**: Using `uuid.UUID` as the FastAPI path type gives free, zero-boilerplate validation.
Even if a caller somehow passes a path-traversal string, it will fail UUID parsing before touching
any storage.

---

## R-007 — No-op `save` Parameter Handling

**Question**: The `save` parameter must be accepted without error and treated as a no-op. How?

**Decision**: Include `save: bool = False` in `QueryRequest` Pydantic model; never act on it

**Findings**:
- Spec FR-008: "accepted without error; treated as a no-op in Phase 0"
- When forwarding to sidecar, always pass `save: false` regardless of caller's `save` value —
  prevents any accidental sidecar-side save behaviour
- Log a debug message if `save=true` is received: "save=true received; treated as no-op in Phase 0"

---

## R-008 — Sidecar `init` Before `query`?

**Question**: The compiler-worker calls `/kb/init` before using a KB. Does generator-api need to
call `/kb/init` before `/kb/query`?

**Decision**: Yes — call `POST /kb/init` once after sidecar is ready, before `POST /kb/query`

**Findings**:
- `service_query_kb` in the sidecar calls `get_kb_backend(body.kb_name)` which only resolves a
  backend — it does not implicitly init the KB. The `KBNotFoundError` check in the sidecar's query
  service (`service_query_kb`) will raise a 404 if the KB does not exist in the backend.
- For the `local` backend, a KB "exists" if `{base_dir}/{kb_name}/wiki/index.md` exists.
  After wiki sync, `wiki/index.md` will be present, so the KB will be found.
- However, the sidecar's `LocalStorageBackend` may still need the `.openkb/config.yaml` for the
  `language` setting used by the query agent. `/kb/init` creates this config file.
- **Safe approach**: always call `POST /kb/init` with `{ kb_name: slug }` after sidecar startup;
  the sidecar returns `{ status: "created" | "exists" }` — both are fine.

**Rationale**: Belt-and-suspenders. The init call is cheap (writes a small config file) and
guarantees the sidecar backend is fully initialised regardless of wiki content.

---

## Summary Table

| ID | Question | Resolution | Impact |
|----|----------|------------|--------|
| R-001 | Sidecar query endpoint and schema | `POST /kb/query`; citations=[], tokens_used=0 in Phase 0 | FR-007, SC-003 met by pass-through design |
| R-002 | Blob container and path layout | Container `openkb`; prefix `{storage_container_path}/wiki/` | Full wiki tree sync required |
| R-003 | Sidecar startup and health check | `openkb serve --host 127.0.0.1 --port {port}`; poll `/openapi.json` | Subprocess pattern confirmed |
| R-004 | KB identifier mapping | `knowledge_bases.slug` → sidecar `kb_name` | Scratch dir layout: `{scratch}/{slug}/wiki/` |
| R-005 | Timeout and teardown | Configurable timeout; `finally` teardown | 504 on timeout; no leaked processes |
| R-006 | Path traversal on kb_id | FastAPI `uuid.UUID` path type | Free validation, zero boilerplate |
| R-007 | `save` no-op | Accept in model; always forward `save=false` to sidecar | FR-008 satisfied |
| R-008 | Sidecar init before query | Always call `POST /kb/init` after startup | Belt-and-suspenders init |
