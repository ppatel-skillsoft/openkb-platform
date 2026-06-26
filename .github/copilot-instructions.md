# OpenKB Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-06-26

## Active Technologies

- **Language**: Python 3.12 — `from __future__ import annotations` in every module
- **CLI**: Click 8.4.0 (`openkb/cli.py`) — all commands use `@cli.command()` + `@click.pass_context`
- **LLM routing**: LiteLLM 1.87.2 + OpenAI Agents SDK 0.17.3
- **HTTP API** (feature `001-fastapi-http-api`): FastAPI 0.137.2 + uvicorn[standard] 0.49.0; Pydantic v2 required
- **Storage backends**: `LocalStorageBackend` (pathlib + portalocker); `AzureBlobStorageBackend` (azure-storage-blob 12.30.0 async)
- **Testing**: pytest 9.0.3 + pytest-asyncio 1.3.0 + httpx 0.28.1 (API tests)
- **MCP Server** (feature `009-fastmcp-kb-server`): fastmcp==3.4.2 (Streamable HTTP transport); `mcp_server/` package; lifespan pattern with httpx.AsyncClient; `mcp.http_app()` ASGI factory served by uvicorn on port 8002
- **Ingestion retry**: tenacity==9.1.2 — exponential backoff (base 2s, max 60s, 5 retries) for OpenAI 429 errors; asyncio.Semaphore(3) for concurrency ceiling

## Project Structure

```text
openkb/
├── cli.py               # all Click commands; thin adapters over services/
├── config.py            # load_config(), save_config(), DEFAULT_CONFIG
├── locks.py             # kb_ingest_lock(), kb_read_lock(), atomic_write_*
├── state.py             # HashRegistry
├── schema.py            # PAGE_CONTENT_DIRS, AGENTS_MD, INDEX_SEED
├── converter.py         # convert_document() → ConvertResult
├── url_ingest.py        # fetch_url_to_raw(), looks_like_url()
├── storage/             # NEW: StorageBackend ABC + Local/Azure implementations
├── services/            # NEW: service_init_kb, service_add_document, etc.
└── api/                 # NEW: FastAPI app, Pydantic models, route handlers

tests/
├── unit/                # NEW: storage backends, service functions
├── integration/         # NEW: API route handlers (httpx.AsyncClient + ASGITransport)
└── contract/            # NEW: response schema assertions
```

## Commands

```bash
# Run tests
pytest

# Run tests for a specific module
pytest tests/unit/test_storage_local.py -v

# Install with API extras (required for openkb serve)
uv run -- uv sync --extra api

# Start API server
openkb serve --host 0.0.0.0 --port 8000

# Lint (if configured)
ruff check openkb/
```

## Code Style

- `from __future__ import annotations` at top of every module
- `logger = logging.getLogger(__name__)` — no `print()` in library code
- Type-annotate all public functions; avoid `Any` except at genuine boundaries
- All Pydantic models use v2 (`field_validator`, `model_config`)
- Route handlers contain **zero** business logic — delegate entirely to service functions
- Service functions raise custom exceptions (`KBNotFoundError`, `LLMError`, etc.) — never `HTTPException`
- All production dependencies pinned to exact versions in `pyproject.toml` with rationale comments

## Key Design Decisions (feature 001-fastapi-http-api)

- **StorageBackend abstraction**: `openkb/storage/base.py` ABC; `LocalStorageBackend` uses `pathlib` + `portalocker`; `AzureBlobStorageBackend` uses Azure Blob Lease for distributed locking
- **Service layer**: `openkb/services/` — five async functions extracted from `cli.py`; return plain dataclasses (not Pydantic models)
- **CLI-API bridge**: `LocalStorageBackend` exposes `.kb_dir` property for passing to path-based compiler functions; Azure backend uses `.local_working_dir()` async context manager (download → process → upload)
- **Backend selection**: `OPENKB_STORAGE_BACKEND=local|azure` env var; no code changes required to switch
- **Validation parity**: Pydantic `field_validator` in request models mirrors `_coerce_model`/`_coerce_language` from `cli.py`

## Key Design Decisions (feature 009-fastmcp-kb-server)

- **MCP server is a thin proxy**: all RAG/LLM logic stays in `generator-api`; `mcp_server/` only translates MCP tool calls to HTTP requests
- **FastMCP 3.4.2 patterns**: `@lifespan` for `httpx.AsyncClient` singleton; `@mcp.custom_route("/health")` for Docker healthcheck; `mcp.http_app()` ASGI factory for uvicorn deployment
- **Two tools only**: `ask_kb` (proxies to `generator-api`) and `list_kbs` (queries Postgres directly) — no write, compilation, or admin tools
- **Streamable HTTP transport**: primary transport on port 8002; STDIO clients use `uvx fastmcp run http://localhost:8002/mcp` as a bridge
- **Rate-limit strategy**: `tenacity` exponential backoff for 429/5xx + `asyncio.Semaphore(3)` + 200ms inter-submission delay in `scripts/ingest_marketing_kb.py`
- **`marketing_kb/` gitignored**: document content never committed; ingestion is a local-only one-shot setup step

## Recent Changes

- 001-fastapi-http-api: Added StorageBackend abstraction, FastAPI service layer, `openkb serve` command
- 009-fastmcp-kb-server: Added FastMCP 3.4.2 MCP server, ingestion script with rate-limit strategy, Docker Compose `mcp-server` service on port 8002

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
