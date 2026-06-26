# Research: FastMCP Knowledge Base Server

**Phase**: 0 — Research & Decision Log
**Branch**: `feature/009-fastmcp-kb-server`
**Date**: 2026-06-26

---

## Decision 1: FastMCP Version

**Decision**: Pin `fastmcp==3.4.2` (latest stable as of 2026-06-26).

**Rationale**: 3.x introduced the `lifespan` decorator pattern, the `@mcp.custom_route` health-check API, native `mcp.http_app()` ASGI factory, and clean Context dependency injection — all needed for a production-grade, Docker-hosted server.

**Alternatives considered**:
- `fastmcp>=2.x` — missing native `lifespan` composability and `custom_route`; would require manual Starlette plumbing.
- Unpinned `fastmcp` — violates constitution Principle II (supply-chain discipline: all production deps must be pinned).

---

## Decision 2: Transport Strategy

**Decision**: HTTP transport (`mcp.http_app()` → uvicorn) as the **primary and only runtime transport** inside Docker Compose. STDIO is documented as a local wrapper that pipes to the HTTP server.

**Rationale**: The MCP server must be accessible to multiple networked clients (Claude Desktop via SSE bridge, GitHub Copilot, Cursor) simultaneously. A shared HTTP endpoint in the Compose network eliminates per-client process spawning. FastMCP's Streamable HTTP transport is the recommended successor to SSE and is supported by all modern MCP hosts.

For STDIO clients (Claude Desktop), the host connects with:
```json
{
  "command": "uvx",
  "args": ["fastmcp", "run", "http://localhost:8002/mcp"]
}
```
This allows the STDIO client to proxy through the HTTP server without a second process.

**Alternatives considered**:
- STDIO-only: would require one process per MCP host connection; not suitable for Docker-hosted multi-client use.
- SSE: deprecated as of FastMCP 3.x; not recommended for new servers.

---

## Decision 3: Server Package Location

**Decision**: New top-level package `mcp_server/` at repository root, following the `generator_api/` and `compiler_worker/` convention.

**Rationale**: The MCP server is a distinct service with its own Dockerfile, config, and lifecycle — not a sub-module of `generator_api`. Mirroring the existing service package layout keeps the repo structure consistent.

**Alternatives considered**:
- Embedding inside `generator_api/`: violates single-responsibility; MCP transport concerns are distinct from HTTP query concerns.
- `services/mcp_server/`: adds unnecessary nesting not used by other services in this repo.

---

## Decision 4: MCP Tool Surface — Two Tools Only

**Decision**: Expose exactly **two tools**:
1. `ask_kb(kb_id: str, question: str) -> KBAnswer` — query a specific KB.
2. `list_kbs() -> list[KBSummary]` — enumerate ready KBs.

**Rationale**: Every tool injected into an MCP host's context window costs tokens. Limiting to two read-only tools preserves context budget, reduces attack surface, and aligns with FR-004 (no write/admin tools). `list_kbs` enables agent self-selection of the correct KB without out-of-band knowledge.

**Why not a Resource for `list_kbs`?**: FastMCP Resources are passive data mounts (URI-based) appropriate for config files and static content. `list_kbs` involves a live DB query and changes frequently; the Tool abstraction with active invocation is more semantically appropriate and better supported across MCP hosts (some hosts do not fetch Resources automatically).

**Alternatives considered**:
- `get_kb_info(kb_id)` tool: redundant given `list_kbs` already provides summaries.
- Tools for document ingestion: explicitly out of scope (FR-004).

---

## Decision 5: Downstream Communication Pattern

**Decision**: The MCP server communicates with `generator-api` over HTTP using `httpx.AsyncClient`, initialised once at server lifespan start (using FastMCP's `@lifespan` decorator) and stored in the lifespan context.

**Rationale**: A singleton `httpx.AsyncClient` with connection pooling is far more efficient than per-request client construction. The FastMCP `@lifespan` pattern (new in 3.0) provides structured startup/teardown and exposes the client via `ctx.lifespan_context["http_client"]`, ensuring clean teardown on server shutdown.

**Alternatives considered**:
- Per-request `httpx.AsyncClient()`: no connection reuse, higher latency.
- Calling generator-api indirectly via DB/Blob: bypasses the sidecar lifecycle managed by generator-api and duplicates its query logic.

---

## Decision 6: Rate-Limit Strategy for Ingestion

**Decision**: The ingestion script uses:
1. **`tenacity`** for per-document retry with exponential backoff (base 2s, multiplier 2, max 60s, up to 5 retries) specifically for HTTP 429 and 5xx responses.
2. **`asyncio.Semaphore`** to cap concurrent in-flight compilation submissions (default: 3).
3. **Pre-submission delay**: 200 ms between each document submission regardless of concurrency to smooth the request rate.

**Rationale**: OpenAI 429 (Too Many Requests) errors are transient; exponential backoff with jitter recovers gracefully. The semaphore prevents bursty parallel submissions that would overwhelm the rate limit even with retries. The 200 ms inter-submission delay adds a baseline throttle that's imperceptible to a human running the script but halves the peak request rate.

**Alternatives considered**:
- Token bucket algorithm: more accurate but requires a dependency (`ratelimit` or manual implementation); overkill for a one-shot ingestion script.
- Sequential (no concurrency): correct but unnecessarily slow for large document sets.

---

## Decision 7: Ingestion Script Location and Invocation

**Decision**: `scripts/ingest_marketing_kb.py` — a standalone async Python script invokable with `uv run python scripts/ingest_marketing_kb.py`. Configuration via env vars (matching the Compose `.env` file) and a single `--kb-dir` argument.

**Rationale**: Consistent with the existing `scripts/` directory pattern in this repo. Using `uv run` ensures the script runs in the project's managed virtual environment. Env-var configuration means the script works with both the local Compose `.env` and any CI/cloud override without code changes.

**Alternatives considered**:
- Click CLI command registered in `pyproject.toml`: adds permanent machinery for a one-shot operational script; unnecessary overhead.
- Baked into a Docker Compose `init` container: harder to re-run ad-hoc, harder to debug.

---

## Decision 8: Health Check Endpoint

**Decision**: The `mcp-server` exposes `GET /health` via `@mcp.custom_route("/health")` returning `{"status": "ok"|"degraded", "generator_api": "ok"|"error"}`.

**Rationale**: FastMCP 3.x provides `@mcp.custom_route` as the idiomatic way to add non-MCP HTTP routes alongside the MCP endpoint. This is intentionally unauthenticated (FastMCP design: custom routes bypass auth middleware) — correct for a Docker Compose healthcheck. The check performs a lightweight `GET /health` call to `generator-api` to confirm downstream reachability.

**Alternatives considered**:
- Mounting inside a FastAPI app for more route control: unnecessary complexity for a single health route.
- TCP-only healthcheck (`nc -z`): does not verify application-level readiness.

---

## Decision 9: Docker Compose Port Assignment

**Decision**: `mcp-server` binds to port **8002** on the host (`8002:8002`). MCP endpoint is `http://localhost:8002/mcp`.

**Rationale**: Port 8000 (`api`) and 8001 (`generator-api`) are already allocated. 8002 is the natural next increment and follows the project's incrementing-port convention.

---

## Decision 10: `marketing_kb/` Gitignore

**Decision**: Add `marketing_kb/` to `.gitignore`. No document content, metadata, or derived index files from this directory will ever be committed.

**Rationale**: The user explicitly stated the documents are not to be committed. Adding to `.gitignore` ensures accidental `git add .` never captures them. This also aligns with constitution Principle II (no sensitive data in source).
