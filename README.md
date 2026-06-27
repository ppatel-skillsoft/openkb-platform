# openkb-platform

Service layer for running OpenKB at scale — multi-tenant Generator API, async Compiler Worker, MCP Server for AI agents, and a local-first Docker Compose stack.

## Services

| Service | Port | Description |
|---------|------|-------------|
| `generator_api` | 8001 | FastAPI service — query proxy that manages per-KB `openkb serve` sidecars, and document lifecycle (delete) |
| `compiler_worker` | — | Async worker that polls a Postgres job queue (SKIP LOCKED) and runs `openkb compile` per document |
| `mcp_server` | 8002 | FastMCP server — per-KB `/{kb_slug}/mcp` endpoints, one `ask` tool per KB, for AI agents |
| `openkb` sidecar | 8000 | One `openkb serve` process per active KB, spawned on demand by the generator API |

The core `openkb` CLI and Python package lives in [openkb-core](https://github.com/ppatel-skillsoft/openkb-core), installed as a pip dependency from a pinned git tag.

## Requirements

- Docker + Docker Compose
- A `.env` file (copy from `.env.example`)

## Quick Start

```bash
cp .env.example .env
docker compose up -d
```

Services start on:
- MCP Server: `http://localhost:8002/{kb_slug}/mcp` (e.g. `http://localhost:8002/marketing-kb/mcp`)
- Generator API: `http://localhost:8001`

## MCP Server

Each knowledge base gets its own MCP endpoint at `/{kb_slug}/mcp`. Connect your AI agent directly to the KB you want — no discovery step needed, no context bloat.

The endpoint exposes a single tool:

| Tool | Description |
|------|-------------|
| `ask` | Ask a natural-language question and get a grounded answer with citations from the knowledge base |

The KB slug is the friendly name used when the knowledge base was initialised (e.g. `marketing-kb`). The endpoint is lazily created on first request and cached for subsequent requests.

### Claude Desktop configuration

```json
{
  "mcpServers": {
    "marketing-kb": {
      "url": "http://localhost:8002/marketing-kb/mcp"
    }
  }
}
```

### Cursor / VS Code / GitHub Copilot configuration

Add to `.cursor/mcp.json`, `.vscode/mcp.json`, or `.github/copilot/mcp.json`:

```json
{
  "servers": {
    "marketing-kb": {
      "url": "http://localhost:8002/marketing-kb/mcp"
    }
  }
}
```

Replace `marketing-kb` with your KB slug. Add one entry per KB you want to expose.

## Generator API

### Query a knowledge base

```
POST /kbs/{kb_id}/query
{"question": "What solutions does Skillsoft offer for AI governance?"}
```

### Delete a document

```
DELETE /kbs/{kb_id}/documents/{doc_id}
```

Removes the document without any LLM calls: soft-deletes the DB row, deletes the document's summary blob, and rebuilds `index.md` from remaining documents. Returns `204 No Content` (idempotent).

## Ingesting Documents

Use the included ingestion script to ingest documents into the pipeline:

```bash
# Dry-run (no DB writes, no uploads) — verify files will be found
uv run python scripts/ingest_marketing_kb.py --dry-run

# Full ingest (requires docker compose stack running)
uv run python scripts/ingest_marketing_kb.py
```

The script uses `asyncio.Semaphore(3)` for parallel blob uploads and tenacity retry with exponential backoff for OpenAI rate limits (429). Job enqueues are staggered with a 200 ms delay.

Documents are placed in `marketing_kb/` at the repo root — this directory is gitignored and never committed.

## Environment Variables

See `.env.example` for all required and optional variables. Key ones:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Postgres connection string |
| `AZURE_STORAGE_CONNECTION_STRING` | Blob storage (Azurite locally) |
| `OPENKB_CORE_VERSION` | Git tag of openkb-core to use (e.g. `v0.1.0`) |
| `GENERATOR_API_URL` | URL the MCP server uses to proxy queries (default: `http://generator-api:8001`) |

## Running Tests

```bash
# Unit + integration tests (no live services needed)
uv run pytest tests/unit/ tests/integration/ -v

# Isolation tests (requires full docker compose stack)
docker compose --profile test run --rm isolation-tests
```

The isolation test suite validates per-KB content isolation, concurrent query correctness, scratch directory cleanup, and process state isolation.

## Project Structure

```
compiler_worker/        Postgres queue consumer and document compilation pipeline
generator_api/
├── app.py              FastAPI app factory, exception handlers
├── router.py           Route handlers (query, delete document)
├── service.py          Business logic (service_delete_document)
├── blob.py             Blob storage helpers (sync, delete, upload index)
├── exceptions.py       KBNotFoundError, DocumentNotFoundError, BlobSyncError, ...
└── pool.py             Persistent sidecar pool
mcp_server/
├── app.py              Root ASGI app — /health + KBDispatcher
├── dispatcher.py       Per-KB FastMCP routing (/{kb_slug}/mcp)
└── config.py           Settings
scripts/
└── ingest_marketing_kb.py  Ingest documents with rate-limit protection
tests/
├── unit/               Unit tests (mock DB + blob)
├── integration/        Integration tests (ASGITransport + httpx)
└── isolation/          End-to-end isolation suite (requires live stack)
specs/                  Feature specifications and implementation plans
docker-compose.yml      Full local stack
```

## Related

- [openkb-core](https://github.com/ppatel-skillsoft/openkb-core) — the `openkb` Python package
