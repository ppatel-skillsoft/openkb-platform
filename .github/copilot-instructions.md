# OpenKB Development Guidelines

Last updated: 2026-06-27

## Active Technologies

- **Language**: Python 3.12 — `from __future__ import annotations` in every module
- **HTTP API**: FastAPI 0.137.2 + uvicorn[standard] 0.49.0; Pydantic v2 required
- **Database**: SQLAlchemy 2.0 (asyncio) + asyncpg 0.30.0 + Postgres
- **Blob Storage**: azure-storage-blob 12.30.0 (async) — Azurite locally
- **MCP Server**: fastmcp==3.4.2 (Streamable HTTP transport); per-KB `/{kb_slug}/mcp` routing
- **Testing**: pytest 9.0.3 + pytest-asyncio 1.3.0 + httpx 0.28.1 (ASGITransport for integration tests)
- **Ingestion retry**: tenacity==9.1.2 — exponential backoff (base 2s, max 60s, 5 retries) for OpenAI 429 errors; `asyncio.Semaphore(3)` concurrency ceiling

## Project Structure

```text
generator_api/
├── app.py              FastAPI app factory; exception handlers (KBNotFoundError, DocumentNotFoundError, ...)
├── router.py           Route handlers — POST /kbs/{kb_id}/query, DELETE /kbs/{kb_id}/documents/{doc_id}
├── service.py          Business logic — service_delete_document()
├── blob.py             Blob helpers — sync_wiki_tree, rebuild_index_md, delete_summary_blob, upload_index_to_blob
├── exceptions.py       KBNotFoundError, DocumentNotFoundError, BlobSyncError, SidecarStartError, SidecarQueryError
├── config.py           Settings (pydantic-settings); get_settings() lru_cache
├── db.py               get_db() async session dependency; check_postgres()
├── pool.py             SidecarPool — persistent per-KB sidecar pool
└── sidecar.py          SidecarProcess — subprocess lifecycle

compiler_worker/
├── worker.py           Main loop — polls Postgres queue with SKIP LOCKED
├── job.py              Per-document compilation job
├── queue_client.py     Atomic job claim via DELETE … RETURNING
└── sidecar.py          Compiler sidecar subprocess wrapper

mcp_server/
├── app.py              Root ASGI app — GET /health + KBDispatcher fallthrough
├── dispatcher.py       KBDispatcher — lazy per-KB FastMCP creation; _ManagedApp lifespan wrapper
├── config.py           Settings — generator_api_url, query_timeout_s, mcp_host, mcp_port
├── db.py               check_postgres() for health endpoint
└── exceptions.py       KBNotFoundError, KBNotReadyError, GeneratorAPIError

scripts/
└── ingest_marketing_kb.py  One-shot ingestion with rate-limit protection

tests/
├── unit/               No live services — mock DB and blob
│   ├── generator_api/  test_blob_helpers.py, test_service.py
│   └── mcp_server/     test_dispatcher.py
├── integration/        ASGITransport + httpx — no live services
│   ├── generator_api/  test_delete_document.py
│   └── mcp_server/     test_mcp_server_http.py
└── isolation/          Requires full docker compose stack
```

## Commands

```bash
# Run unit + integration tests (no live services needed)
uv run pytest tests/unit/ tests/integration/ -v

# Run a specific test file
uv run pytest tests/unit/generator_api/test_service.py -v

# Install all extras for local dev
uv sync --extra dev --extra mcp

# Start full local stack
docker compose up -d

# Ingest marketing documents (marketing_kb/ dir must exist locally)
uv run python scripts/ingest_marketing_kb.py --dry-run   # verify
uv run python scripts/ingest_marketing_kb.py             # ingest
```

## Code Style

- `from __future__ import annotations` at top of every module
- `logger = logging.getLogger(__name__)` — no `print()` in library code
- Type-annotate all public functions; avoid `Any` except at genuine boundaries
- All Pydantic models use v2 (`field_validator`, `model_config`)
- Route handlers contain **zero** business logic — delegate entirely to service functions
- Service functions raise custom exceptions (`KBNotFoundError`, `DocumentNotFoundError`, etc.) — never `HTTPException`
- All production dependencies pinned to exact versions in `pyproject.toml`

## Key Design Decisions (feature 009 — FastMCP KB server)

- **Per-KB routing**: `/{kb_slug}/mcp` — one FastMCP instance per KB; single `ask(question)` tool; no discovery overhead
- **Slug not UUID**: URL uses the friendly KB name (e.g. `marketing-kb`), not the internal UUID; UUID is captured in closure and never exposed to the LLM
- **`KBDispatcher`** (`mcp_server/dispatcher.py`): lazy per-KB FastMCP creation with `asyncio.Lock` cache; `_ManagedApp` wrapper drives the ASGI lifespan protocol as a background task before serving requests (required for FastMCP's `StreamableHTTPSessionManager`)
- **Thin proxy**: all RAG/LLM logic stays in `generator_api`; `mcp_server` only translates MCP tool calls to HTTP requests via `httpx.AsyncClient` in the lifespan context
- **`marketing_kb/` gitignored**: document content never committed; ingestion is a local-only one-shot setup step

## Key Design Decisions (feature 011 — DELETE document endpoint)

- **Zero LLM calls**: removal is: soft-delete DB row → delete `wiki/summaries/{slug}.md` blob → rebuild `index.md`
- **Summary blob only**: concepts/entities blobs are left intact (cheap; may relate to other documents); only the uniquely-named summary blob is removed
- **Idempotent**: second `DELETE` on an already-deleted doc returns `204` immediately without any storage ops
- **`service_delete_document()`** (`generator_api/service.py`): owns all business logic; route handler is a thin dispatcher
- **Empty-KB edge case**: if all documents are deleted, `sync_wiki_tree` raises `BlobSyncError("no blobs found")`; service writes a blank-section `index.md` instead of re-raising

## Recent Changes

- **011** — `DELETE /kbs/{kb_id}/documents/{doc_id}`: soft-delete + summary blob removal + index rebuild; zero LLM calls; `DocumentNotFoundError` → 404
- **009** — FastMCP MCP server on port 8002; per-KB `/{kb_slug}/mcp` routing; single `ask` tool; `KBDispatcher` with lazy lifespan management

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
