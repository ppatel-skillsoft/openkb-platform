# openkb-platform

Service layer for running OpenKB at scale — multi-tenant Generator API, async Compiler Worker, MCP Server for AI agents, and a local-first Docker Compose stack.

## Services

| Service | Port | Description |
|---------|------|-------------|
| `generator_api` | 8001 | FastAPI service that accepts query requests and manages per-KB `openkb serve` sidecars |
| `compiler_worker` | — | Async worker that polls a Postgres job queue (SKIP LOCKED) and runs `openkb compile` per document |
| `mcp_server` | 8002 | FastMCP server — exposes `ask_kb` and `list_kbs` tools for AI agents (Claude, Cursor, GitHub Copilot) |
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
- MCP Server: `http://localhost:8002/mcp`
- Generator API: `http://localhost:8001`
- OpenKB sidecar API: `http://localhost:8000`

## MCP Server

The `mcp-server` service exposes two tools consumable by any MCP-compatible host:

| Tool | Description |
|------|-------------|
| `ask_kb` | Ask a question against a specific knowledge base and get a grounded answer with citations |
| `list_kbs` | List all available knowledge bases with document counts |

### Claude Desktop configuration

```json
{
  "mcpServers": {
    "openkb": {
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

### Cursor / VS Code configuration

Add to `.cursor/mcp.json` or `.vscode/mcp.json`:

```json
{
  "servers": {
    "openkb": {
      "url": "http://localhost:8002/mcp"
    }
  }
}
```

## Ingesting Documents

Use the included ingestion script to ingest documents into the pipeline:

```bash
# Dry-run (no DB writes, no uploads) — verify files will be found
uv run python scripts/ingest_marketing_kb.py --dry-run

# Full ingest (requires docker compose stack running)
uv run python scripts/ingest_marketing_kb.py
```

The script uses `asyncio.Semaphore(3)` for parallel blob uploads and tenacity retry for transient Azure errors. Job enqueues are staggered with a 1 s delay to avoid OpenAI rate-limit bursts in the compiler-worker.

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
# Unit + integration tests
uv run pytest tests/unit/ tests/integration/ -v

# Isolation tests (requires services running)
docker compose --profile test run --rm isolation-tests
```

The isolation test suite validates:
- Per-KB content isolation (no cross-contamination between knowledge bases)
- Concurrent query correctness
- Scratch directory isolation and cleanup
- Process state isolation across sequential queries

## Project Structure

```
compiler_worker/             Postgres queue consumer and document compilation pipeline
generator_api/               FastAPI app, route handlers, sidecar lifecycle management
mcp_server/                  FastMCP server with ask_kb and list_kbs tools
scripts/ingest_marketing_kb.py  Ingest documents into the pipeline
tests/isolation/             End-to-end isolation test suite
docker-compose.yml           Full local stack
specs/                       Feature specifications and implementation plans
```

## Related

- [openkb-core](https://github.com/ppatel-skillsoft/openkb-core) — the `openkb` Python package
